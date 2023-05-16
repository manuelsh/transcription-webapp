import os
import pydub
import tempfile
import uuid
import sqlite3
import boto3
import requests
import json
import re
import docx
import fpdf
from zipfile import ZipFile
from emails import send_email


# Database model
# Latest update: 2023-03-09
# File table
# Columns:
# - user_id: the user's id, coming form firebase
# - file_name_stored: the file's name stored in the server
# - file_name: the original file's name
# - file_length: the length of the file in seconds
# - file_status: the processing status of the file, can be 'pending', 'processing', 'processed', 'error'
# - payment_status: the status of the payment, can be 'pending', 'paid'
# - payment_id: the id of the payment, coming from stripe (client_secret)
# - rating: the rating of the transcription, can be null

# --- Main variables from environment variables
USERS_FILES_PATH = os.environ["USERS_FILES_PATH"]+"/"
DATABASE_PATH = os.environ["DATABASE_PATH"]+"/"
DATABASE_FILE_NAME = os.environ["DATABASE_FILE_NAME"]
NEW_USER_FREE_MINUTES = float(os.environ["NEW_USER_FREE_MINUTES"])

# AWS credentials and info
AWS_CREDENTIALS_ADDRESS = os.environ["AWS_CREDENTIALS_ADDRESS"]
S3_BUCKET = os.environ["S3_BUCKET"]
AWS_REGION = os.environ["AWS_REGION"]
JOB_QUEUE = os.environ["JOB_QUEUE"]
JOB_DEFINITION = os.environ["JOB_DEFINITION"]

# --- Utils functions

# Make general SQL queries


def execute_sql(sql, fetch=False):
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute(sql)
    if fetch:
        result = cur.fetchall()
    conn.commit()
    conn.close()
    if fetch:
        return result


# Check if it is a sound media file
def is_media_file(file_obj) -> tuple:
    try:
        temp_file = tempfile.NamedTemporaryFile()
        temp_file.write(file_obj.read())
        file_info = pydub.utils.mediainfo(temp_file.name)
        if (file_info['sample_rate'] == None):
            return (False, None, None)
        elif file_info['duration'] == 'N/A':
            return (False, None, None)
        else:
            return (True, temp_file, file_info)
    except:
        return (False, None, None)


# converts file to flac, 16000Hz, mono
def converts_file(file):
    audio_file = pydub.AudioSegment.from_file(
        file.name).set_frame_rate(16000).set_channels(1)
    return audio_file


# takes an "audiosegment" object, stores file in folder with unique name, and returns new file name
def stores_file(audio_file, user_id) -> str:
    file_name = user_id + "_" + str(uuid.uuid4()) + ".flac"

    # Stores file in a file, upload to S3, and removes the file
    audio_file.export(USERS_FILES_PATH + file_name, format="flac")
    s3 = boto3.resource('s3')
    s3.Bucket(S3_BUCKET).upload_file(USERS_FILES_PATH + file_name, file_name)
    os.remove(USERS_FILES_PATH + file_name)
    return file_name


def records_file_in_db(file_name_stored, file_name, user_id, file_length) -> None:
    # records file name, user_id and status=pending in database
    execute_sql("INSERT INTO files VALUES ('{}','{}','{}','{}','{}','{}','{}','{}')".format(
        user_id, file_name_stored, file_name, file_length, "pending", "pending", "pending", None))


def checks_file_duplicated(file_name, user_id, file_length) -> tuple:
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute("SELECT file_name FROM files WHERE user_id = ? AND file_name = ? AND file_length = ? AND payment_status = 'pending'",
                (user_id, file_name, file_length))
    duplicated_file_info = cur.fetchone()
    conn.close()
    if duplicated_file_info:
        return (True, duplicated_file_info)
    else:
        return (False, None)


# Processes uploaded file: checks it, converts it, and stores the information in the database
def file_processor(file, user_id) -> dict:
    status, temp_file, file_info = is_media_file(file.file)

    if status:
        file_duplicated, duplicated_file_info = checks_file_duplicated(file.filename,
                                                                       user_id,
                                                                       file_info['duration'])

        if not file_duplicated:
            file_converted = converts_file(temp_file)
            file_name_stored = stores_file(file_converted, user_id)
            records_file_in_db(file_name_stored, file.filename,
                               user_id, file_info['duration'])
            return {"status": True,
                    "message": '"'+file.filename+'" is a media file and will be transcribed.',
                    "file_length": file_info['duration']}
        else:
            return {"status": "duplicated_in_cart",
                    'message': '"'+file.filename+'" is already in the queue.',
                    "file_info": duplicated_file_info}
    else:
        return {"status": False}


# Returns all pending payment files from a user id, their length, the total length and the total cost
def get_pending_payment_files(user_id) -> dict:

    # Gets all pending payment files from a user id
    files = execute_sql(
        "SELECT file_name, file_length, file_name_stored FROM files WHERE user_id = '{}' AND payment_status = 'pending'".format(user_id), fetch=True)

    if len(files) > 0:
        # Puts data in a dictionary, file by file
        files = [{"file_name": file[0],
                  "file_length": file[1],
                  "file_name_stored": file[2],
                  } for file in files]

        total_length = sum([file["file_length"] for file in files])
        total_files = len(files)

        return {"files": files,
                "total_length": total_length,
                "total_files": total_files}
    else:
        return {"files": [],
                "total_length": 0,
                "total_files": 0}


# Adds the client_secret to a set of files for a payment to be confirmed
def add_payment_id_to_files(user_id, files, payment_id) -> None:
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    for file in files:
        cur.execute("UPDATE files SET payment_id = ? WHERE user_id = ? AND file_name_stored = ? AND payment_status = 'pending'",
                    (payment_id, user_id, file["file_name_stored"]))
    conn.commit()
    conn.close()


# Changes a set of files with given payment_id to "paid" status
def change_files_status_to_paid(payment_id) -> None:
    execute_sql(
        "UPDATE files SET payment_status = 'paid' WHERE payment_id = '{}'".format(payment_id))


# Removes payment id to a set of files, and change it to some text
def remove_payment_id(payment_id, text) -> None:
    execute_sql("UPDATE files SET payment_id = '{}' WHERE payment_id = '{}'".format(
        text, payment_id))


# Removes all files from user cart
# It will change the status of the files to "cancelled" and the payment status to "cancelled"
# Will also remove the files from the server
def remove_all_files_from_cart(user_id) -> dict:
    try:
        # Gets all pending payment files from a user id
        files = execute_sql(
            "SELECT file_name_stored FROM files WHERE user_id = '{}' AND payment_status = 'pending'".format(user_id), fetch=True)

        # Removes files from server
        for file in files:
            delete_file_from_s3(file[0])

        # Changes status of files to "cancelled" and payment status to "cancelled"
        execute_sql("UPDATE files SET payment_status = 'cancelled', file_status = 'cancelled' WHERE user_id = '{}' AND payment_status = 'pending'".format(user_id))

        return {'status': True}

    # Returns false and error message if something goes wrong
    except Exception as e:
        return {'status': False, 'error_message': str(e)}


# Get the files of a user to show the status and be able to donwload them
# Returns a list of dictionaries with the file name, the file length,
# the file status and the payment status
def get_files_info(user_id) -> list:
    files = execute_sql(
        "SELECT file_name, file_name_stored, file_length, file_status, payment_status FROM files WHERE user_id = '{}'".format(user_id), fetch=True)
    files = [{"file_name": file[0],
              "file_name_stored": file[1],
              "file_length": file[2],
              "file_status": file[3],
              "payment_status": file[4]} for file in files]

    return files


def get_file_info(user_id, file_name_stored) -> dict:
    file = execute_sql("SELECT file_name, file_length, file_status, payment_status FROM files WHERE user_id = '{}' AND file_name_stored = {}".format(
        user_id, file_name_stored), fetch=True)
    file = {"file_name": file[0][0],
            "file_length": file[0][1],
            "file_status": file[0][2],
            "payment_status": file[0][3]}

    return file


# Update file status
def update_file_status(file_name_stored, new_status) -> None:
    execute_sql("UPDATE files SET file_status = '{}' WHERE file_name_stored = '{}'".format(
        new_status, file_name_stored))


# Starts the transcription process to the files with the given payment_id, payment_status="paid" and file_status="pending"
def start_transcriptions(client_secret) -> None:
    files = execute_sql("SELECT file_name_stored FROM files WHERE payment_id = '{}' AND payment_status = 'paid' AND file_status = 'pending'".format(
        client_secret), fetch=True)
    for file in files:
        file_name_stored = file[0]
        update_file_status(file_name_stored, "processing")
        job_response = transcribe_file(file_name_stored)
        print('Job sent. File: '+file_name_stored, flush=True)
        print(job_response, flush=True)
        if job_response['ResponseMetadata']['HTTPStatusCode'] != 200:
            update_file_status(file_name_stored, "error")
            print("Error in job response!!", flush=True)


# Transcribes a file and returns the job response
def transcribe_file(file_name_stored) -> dict:
    # Get the credentials from the instance metadata service
    r = requests.get(AWS_CREDENTIALS_ADDRESS)
    credentials = json.loads(r.text)

    # Get file length
    file_length = execute_sql(
        "SELECT file_length FROM files WHERE file_name_stored = '{}'".format(file_name_stored), fetch=True)[0][0]

    # Gets AWS Batch client
    batch = boto3.client('batch',
                         region_name=AWS_REGION,
                         aws_access_key_id=credentials['AccessKeyId'],
                         aws_secret_access_key=credentials['SecretAccessKey'], aws_session_token=credentials['Token'])

    # Remove characters not allowed in job name from file name
    file_name_clean = re.sub('[^A-Za-z0-9]+', '', file_name_stored)

    # Submits the job to AWS Batch
    job_response = batch.submit_job(
        jobName=(file_name_clean+'__length_' +
                 str(round(file_length))+'_seconds')[0:128],
        jobQueue=JOB_QUEUE,
        jobDefinition=JOB_DEFINITION,
        containerOverrides={
            'environment': [
                {
                    'name': 'FILE_NAME',
                    'value': file_name_stored
                },
                {
                    'name': 'LANGUAGE',
                    'value': 'auto'
                },
                {
                    'name': 'TASK',
                    'value': 'transcribe'
                },
            ],
            'resourceRequirements': [
                {
                    'value': '1',
                    'type': 'GPU',
                }
            ]
        }
    )

    return job_response


# Get file from S3
def get_file_from_s3(file_name: str) -> None:
    # Get the credentials from the instance metadata service
    r = requests.get(AWS_CREDENTIALS_ADDRESS)
    credentials = json.loads(r.text)

    # Gets S3 client
    s3 = boto3.client('s3',
                      region_name=AWS_REGION,
                      aws_access_key_id=credentials['AccessKeyId'],
                      aws_secret_access_key=credentials['SecretAccessKey'], aws_session_token=credentials['Token'])

    # Gets the file from S3
    s3.download_file(S3_BUCKET, file_name, USERS_FILES_PATH+file_name)


# Return transcription from file name stored
def get_transcription_text(file_name_stored: str, include_timestamps=False) -> dict:

    # Downloads the json file from S3
    file_name_with_transcription = file_name_stored+'_result.json'
    get_file_from_s3(file_name_with_transcription)

    # Loads the json file into a dict
    with open(USERS_FILES_PATH+file_name_with_transcription, 'r') as file:
        transcription_json = json.load(file)

    # Returns the transcription text
    if include_timestamps:
        return transcription_json
    else:
        # Join all text segments separated by a space
        # segments: [{"id": 1, "seek": 0, "start": 5.4, "end": 8.6, "text": "text"...}{...}]
        text_to_return = ' '.join(
            [segment['text'] for segment in transcription_json['segments']])
        return {'transcription': text_to_return}


# Returns a text file with the transcription
def transcription_to_txt(transcription: str, file_name: str) -> str:
    file_path = USERS_FILES_PATH+file_name+'.txt'
    with open(file_path, 'w') as file:
        file.write(transcription)
    return file_path


# Returns a word file with the transcritpion
def transcription_to_docx(transcription: str, file_name: str) -> str:
    file_path = USERS_FILES_PATH+file_name+'.docx'
    doc = docx.Document()
    doc.add_paragraph(transcription)
    doc.save(file_path)
    return file_path


# Returns a pdf file with the transcription
def transcription_to_pdf(transcription: str, file_name: str) -> str:
    file_path = USERS_FILES_PATH+file_name+'.pdf'
    # Creates pdf and ensures that the paragraph splits in lines if it's too long
    pdf = fpdf.FPDF()
    pdf.set_auto_page_break(0)
    pdf.add_page()
    pdf.set_font('Arial', '', 12)
    pdf.multi_cell(0, 5, transcription)
    pdf.output(file_path, 'F')
    return file_path


# Delete file from S3
def delete_file_from_s3(file_name: str) -> None:
    # Get the credentials from the instance metadata service
    r = requests.get(AWS_CREDENTIALS_ADDRESS)
    credentials = json.loads(r.text)

    # Gets S3 client
    s3 = boto3.client('s3',
                      region_name=AWS_REGION,
                      aws_access_key_id=credentials['AccessKeyId'],
                      aws_secret_access_key=credentials['SecretAccessKey'], aws_session_token=credentials['Token'])

    # Deletes the file from S3
    s3.delete_object(Bucket=S3_BUCKET, Key=file_name)


# User management
# Users table
# Columns:
# - user_id: the user's id, coming form firebase
# - user_email: the user's email
# - user_seconds: the amount of seconds the user has available to process files
# - spending: the amount of money the user has spent


def check_if_user_exists(user_id) -> bool:
    user = execute_sql(
        "SELECT user_id FROM users WHERE user_id = '{}'".format(user_id), fetch=True)
    if len(user) == 0:
        return False
    else:
        return True


# Create a user and give it NEW_USER_FREE_MINUTES minutes of free transcription by adding
# them to the user_seconds column
def create_user(user_id, user_email) -> None:
    execute_sql("INSERT INTO users (user_id, user_email, user_seconds, spending) VALUES ('{}', '{}', '{}', '{}')".format(
        user_id, user_email, NEW_USER_FREE_MINUTES*60., 0))


# Get number of user_seconds
def get_user_seconds(user_id) -> int:
    user_seconds = execute_sql(
        "SELECT user_seconds FROM users WHERE user_id = '{}'".format(user_id), fetch=True)[0][0]
    return user_seconds


def change_user_seconds(user_id, new_number_of_user_seconds) -> None:
    execute_sql("UPDATE users SET user_seconds = '{}' WHERE user_id = '{}'".format(
        new_number_of_user_seconds, user_id))


def change_user_seconds_with_client_secret(client_secret, new_number_of_user_seconds) -> None:
    # get the user id from the client secret from the files table
    user_id = execute_sql("SELECT user_id FROM files WHERE payment_id = '{}'".format(
        client_secret), fetch=True)[0][0]
    change_user_seconds(user_id, new_number_of_user_seconds)


# Add ratings of transcriptions to database
def update_file_rating(file_name_stored, rating) -> None:
    execute_sql("UPDATE files SET rating = '{}' WHERE file_name_stored = '{}'".format(
        rating, file_name_stored))


def get_file_rating(file_name_stored):
    rating = execute_sql("SELECT rating FROM files WHERE file_name_stored = '{}'".format(
        file_name_stored), fetch=True)
    if len(rating) == 0:
        return None
    else:
        return rating[0][0]

# Send email to user once the transcription is ready


def send_finished_email(file_name_stored):
    # Get the user id from the file_name_stored
    user_id = execute_sql("SELECT user_id FROM files WHERE file_name_stored = '{}'".format(
        file_name_stored), fetch=True)[0][0]
    # Get the user email from the user id
    user_email = execute_sql("SELECT user_email FROM users WHERE user_id = '{}'".format(
        user_id), fetch=True)[0][0]

    # Send email adding a link to see the transcription
    # link will be with the following form:
    # https://www.platic.io/private/transcription?file_id=[file_name_stored]&file_name=[file_name]

    # Get the file name from the file_name_stored
    file_name = execute_sql("SELECT file_name FROM files WHERE file_name_stored = '{}'".format(
        file_name_stored), fetch=True)[0][0]

    # Create the link
    link = 'https://www.platic.io/private/transcription?file_id={}&file_name={}'.format(
        file_name_stored, file_name)

    # Transform the spaces of the link to %20
    link = link.replace(' ', '%20')

    # Send the email
    send_email(user_email, f'Your transcription is ready! - {file_name}',
               f'''The file: 
               {file_name}
                has been transcribed.
                Click here to see the transcription: {link}''')


# Get the link of a file in S3, used for audiofiles
def get_link_of_s3_file(file_name) -> str:
    # Get the credentials from the instance metadata service
    r = requests.get(AWS_CREDENTIALS_ADDRESS)
    credentials = json.loads(r.text)

    # Gets S3 client
    s3 = boto3.client('s3',
                      region_name=AWS_REGION,
                      aws_access_key_id=credentials['AccessKeyId'],
                      aws_secret_access_key=credentials['SecretAccessKey'], aws_session_token=credentials['Token'])

    # Get the file url
    file_url = s3.generate_presigned_url(
        ClientMethod='get_object', Params={'Bucket': S3_BUCKET, 'Key': file_name}, ExpiresIn=3600)

    return file_url


def stores_dict_in_json_file(dictionary, file_name):
    result_json = json.dumps(dictionary)
    with open(file_name, 'w') as f:
        f.write(result_json)


def stores_file_in_s3(file_path, file_name) -> str:
    # Stores file in a file, upload to S3, and removes the file
    s3 = boto3.resource('s3')
    s3.Bucket(S3_BUCKET).upload_file(file_path, file_name)
    return True


def update_transcription_text(file_name_stored,
                              segment_number, new_text):
    # Get the transcription json

    transcription_json = get_transcription_text(
        file_name_stored, include_timestamps=True)

    # Update the transcription json which has the following key:
    # segments: [{"id": 1, "seek": 0, "start": 5.4, "end": 8.6, "text": "text"...}{...}]
    transcription_json['segments'][segment_number]['text'] = new_text

    # Upload the transcription json to S3
    json_file_name = file_name_stored+'_result.json'
    stores_dict_in_json_file(
        transcription_json, USERS_FILES_PATH + json_file_name)
    stores_file_in_s3(USERS_FILES_PATH + json_file_name,
                      json_file_name)

    # Delete the transcription json from the server
    os.remove(USERS_FILES_PATH + json_file_name)


def get_all_transcriptions_from_user_in_zip(user_id: str) -> str:
    # Get all the file names that have file_status processed from the user
    file_name_pairs = execute_sql(
        "SELECT file_name_stored, file_name FROM files WHERE user_id = '{}' AND file_status = '{}'".format(user_id, 'processed'), fetch=True)

    # Build all txt files
    for file_name_pair in file_name_pairs:
        transcription = get_transcription_text(
            file_name_pair[0])['transcription']
        transcription_to_txt(transcription, file_name_pair[1])

    # Zip all files
    zip_file_path = USERS_FILES_PATH+user_id+'.zip'
    with ZipFile(zip_file_path, 'w') as zip:
        for file_name_pair in file_name_pairs:
            zip.write(USERS_FILES_PATH+file_name_pair[1]+'.txt',
                      file_name_pair[1]+'.txt')

    # Delete all txt files, note that there may be duplicates
    duplicate_checks = []
    for file_name_pair in file_name_pairs:
        if file_name_pair[1] not in duplicate_checks:
            duplicate_checks.append(file_name_pair[1])
            os.remove(USERS_FILES_PATH+file_name_pair[1]+'.txt')

    return zip_file_path
