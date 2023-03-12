# Fast Api server implementation, which receives files and transcribes them

from fastapi import FastAPI, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from utils import *
import os
import stripe
from pydantic import BaseModel

PRICE_PER_MINUTE = os.environ["PRICE_PER_MINUTE"]
MINIMUM_PAYMENT = os.environ["MINIMUM_PAYMENT"]


# API key for stripe
stripe.api_key = os.environ.get("STRIPE_API_KEY")

# Fast API server
app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Upload file api
@app.post("/uploadfile/")
async def receive_file(file: UploadFile, user_id: str):
    info = file_processor(file, user_id)
    return info


# Get information about files to be transcribed, their length, cost and total cost
@app.get("/getfilestopay/")
async def get_files_to_pay(user_id: str):
    info = get_pending_payment_files(user_id)
    seconds_available = get_user_seconds(user_id)
    # If the user has enough seconds to process the files
    # do not charge the user
    info['seconds_available'] = seconds_available
    if info['total_length'] <= seconds_available:
        info['total_price'] = 0
    else:
        # If the user does not have enough seconds to process the files
        # charge the user
        seconds_to_charge = info['total_length'] - seconds_available
        info['total_price'] = max(
            seconds_to_charge * PRICE_PER_MINUTE, MINIMUM_PAYMENT)
    return info

# Removes all files from cart


@app.get("/cleancart/")
async def clean_cart(user_id: str):
    info = remove_all_files_from_cart(user_id)
    return info


class User(BaseModel):
    user_id: str
    user_email: str


# Stripe payment intent
# Receives user id, user_email
# stores the client secret in the database for each
# file and sends the client secret for stripe
@app.post('/create-payment-intent/')
async def create_payment(user: User):
    # try:
    info = get_pending_payment_files(user.user_id)
    seconds_available = get_user_seconds(user.user_id)

    # If the user has enough seconds to process the files
    # do not charge the user
    if info['total_length'] <= seconds_available:
        add_payment_id_to_files(
            user.user_id, info["files"], user.user_id+'free')

        # Set files as paid and start transcriptions
        change_files_status_to_paid(user.user_id+'free')
        start_transcriptions(user.user_id+'free')

        # Reduce the user's seconds
        change_user_seconds(user.user_id, round(
            seconds_available - info['total_length']))
        return {
            'clientSecret': 'free'
        }
    else:
        # If the user does not have enough seconds to process the files
        # charge the user
        seconds_to_charge = info['total_length'] - seconds_available
        price = max(seconds_to_charge * PRICE_PER_MINUTE, MINIMUM_PAYMENT)

        # Create a PaymentIntent with the order amount and currency

        description = 'Transcription of ' + str(round(info['total_length']/60., 2)) + ' minutes,' + str(
            info['total_files']) + ' files, email: ' + user.user_email

        intent = stripe.PaymentIntent.create(
            amount=round(price*100),
            currency='usd',
            automatic_payment_methods={
                'enabled': True,
            },
            description=description,
            receipt_email=user.user_email
        )

        # Store the client secret in the database for each file
        add_payment_id_to_files(
            user.user_id, info["files"], intent['client_secret'])
        return {
            'clientSecret': intent['client_secret']
        }
        # except Exception as e:
        #     return {'error': str(e)}, 403


# Show files of a user and its status
@app.get("/get-files")
async def get_files(user_id: str):
    info = get_files_info(user_id)
    return info


# Stripe payment confirmation webhook in Fast API
# Once there is confirmation of payment, transcription starts!
@app.post('/webhook')
async def webhook(request: Request):
    # Get the event by verifying the signature using the raw body and secret if webhook signing is configured.
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.environ.get("STRIPE_WEBHOOK_SECRET")
        )
    except ValueError as e:
        # Invalid payload
        return {'status': 'ValueError: ' + str(e)}
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return {'status': 'SignatureVerificationError: ' + str(e)}, 400

    # Handle the checkout.session.completed event and starts the transcriptions
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        client_secret = payment_intent['client_secret']
        # Set files as paid
        change_files_status_to_paid(client_secret)
        start_transcriptions(client_secret)

        # Reduce the user's seconds to zero
        change_user_seconds_with_client_secret(client_secret, 0)

    elif (event['type'] == 'payment_intent.payment_failed') or (event['type'] == 'payment_intent.canceled'):
        payment_intent = event['data']['object']
        remove_payment_id(
            payment_intent['client_secret'], payment_intent['status'])

    return {'status': 'success'}


# Transcription has finished, send email to user and update status in database
class FileInfo(BaseModel):
    file_name_stored: str
    new_file_status: str


@app.post("/transcription-finished")
async def transcription_finished(file_info: FileInfo):
    if (file_info.new_file_status == 'error') or (file_info.new_file_status == 'processed'):
        update_file_status(file_info.file_name_stored,
                           file_info.new_file_status)
        return {'status': 'success'}
    else:
        return {'status': 'error, new_file_status must be error or processed, not ' + file_info.new_file_status}


# Return transcription from a file name stored in the database
@app.get("/get-transcription")
async def get_transcription(file_name_stored: str):
    transcription = get_transcription_text(file_name_stored)
    return transcription

# Checks if user is new or not, and if new it will be added to the database


@app.get('/check-new-user')
async def check_new_user(user_id: str, user_email: str):
    if check_if_user_exists(user_id):
        return {'status': 'user exists'}
    else:
        create_user(user_id, user_email)
        return {'status': 'user added'}
