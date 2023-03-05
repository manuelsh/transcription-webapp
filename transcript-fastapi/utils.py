from io import BytesIO
import os
import pydub
import base64
import tempfile
import uuid
import sqlite3
import boto3
import requests
import json

# Database file model
# Latest update: 2023-02-14
# Columns:
# - user_id: the user's id, coming form firebase
# - file_name_stored: the file's name stored in the server
# - file_name: the original file's name
# - file_length: the length of the file in seconds
# - file_status: the processing status of the file, can be 'pending', 'processing', 'processed', 'error'
# - payment_status: the status of the payment, can be 'pending', 'paid'
# - payment_id: the id of the payment, coming from stripe (client_secret)

# --- Main variables from environment variables
USERS_FILES_PATH = os.environ["USERS_FILES_PATH"]+"/"
DATABASE_PATH = os.environ["DATABASE_PATH"]+"/"
DATABASE_FILE_NAME = os.environ["DATABASE_FILE_NAME"]
PRICE_PER_MINUTE = os.environ["PRICE_PER_MINUTE"]

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


def is_media_file(file_obj):
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


def stores_file(audio_file, user_id):
    file_name = user_id + "_" + str(uuid.uuid4()) + ".flac"

    # Stores file in a file, upload to S3, and removes the file
    audio_file.export(USERS_FILES_PATH + file_name, format="flac")
    s3 = boto3.resource('s3')
    s3.Bucket(S3_BUCKET).upload_file(USERS_FILES_PATH + file_name, file_name)
    os.remove(USERS_FILES_PATH + file_name)
    return file_name


def records_file_in_db(file_name_stored, file_name, user_id, file_length):
    # records file name, user_id and status=pending in database
    execute_sql("INSERT INTO files VALUES ('{}','{}','{}','{}','{}','{}','{}')".format(
        user_id, file_name_stored, file_name, file_length, "pending", "pending", "pending"))


def checks_file_duplicated(file_name, user_id, file_length):
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


def file_processor(file, user_id):
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
def get_pending_payment_files(user_id):

    # Gets all pending payment files from a user id
    files = execute_sql(
        "SELECT file_name, file_length, file_name_stored FROM files WHERE user_id = '{}' AND payment_status = 'pending'".format(user_id), fetch=True)

    # Puts data in a dictionary, file by file
    files = [{"file_name": file[0],
              "file_length": file[1],
              "file_name_stored": file[2],
              "file_price":round(file[1]/60. * float(PRICE_PER_MINUTE), 2)} for file in files]

    total_price = round(sum([file["file_price"] for file in files]), 2)
    total_length = sum([file["file_length"] for file in files])
    total_files = len(files)

    return {"files": files,
            "total_length": total_length,
            "total_price": total_price,
            "total_files": total_files}

# Adds the client_secret to a set of files for a payment to be confirmed


def add_payment_id_to_files(user_id, files, payment_id):
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    for file in files:
        cur.execute("UPDATE files SET payment_id = ? WHERE user_id = ? AND file_name_stored = ? AND payment_status = 'pending'",
                    (payment_id, user_id, file["file_name_stored"]))
    conn.commit()
    conn.close()


# Changes a set of files with given payment_id to "paid" status
def change_files_status_to_paid(payment_id):
    execute_sql(
        "UPDATE files SET payment_status = 'paid' WHERE payment_id = '{}'".format(payment_id))

# Removes payment id to a set of files, and change it to some text


def remove_payment_id(payment_id, text):
    execute_sql("UPDATE files SET payment_id = '{}' WHERE payment_id = '{}'".format(
        text, payment_id))

# Removes all files from user cart
# It will change the status of the files to "cancelled" and the payment status to "cancelled"
# Will also remove the files from the server


def remove_all_files_from_cart(user_id):
    try:
        # Gets all pending payment files from a user id
        files = execute_sql(
            "SELECT file_name_stored FROM files WHERE user_id = {} AND payment_status = 'pending'".format(user_id), fetch=True)

        # Removes files from server
        for file in files:
            os.remove(USERS_FILES_PATH + file[0])

        # Changes status of files to "cancelled" and payment status to "cancelled"
        execute_sql("UPDATE files SET payment_status = 'cancelled', file_status = 'cancelled' WHERE user_id = {} AND payment_status = 'pending'".format(user_id))

        return {'status': True}

    # Returns false and error message if something goes wrong
    except Exception as e:
        return {'status': False, 'error_message': str(e)}


# Get the files of a user to show the status and be able to donwload them
# Returns a list of dictionaries with the file name, the file length,
# the file status and the payment status
def get_files_info(user_id):
    files = execute_sql(
        "SELECT file_name, file_length, file_status, payment_status FROM files WHERE user_id = {}".format(user_id), fetch=True)
    files = [{"file_name": file[0],
              "file_length": file[1],
              "file_status": file[2],
              "payment_status": file[3]} for file in files]

    return files


def get_file_info(user_id, file_name_stored):
    file = execute_sql("SELECT file_name, file_length, file_status, payment_status FROM files WHERE user_id = {} AND file_name_stored = {}".format(
        user_id, file_name_stored), fetch=True)
    file = {"file_name": file[0][0],
            "file_length": file[0][1],
            "file_status": file[0][2],
            "payment_status": file[0][3]}

    return file

# Update file status


def update_file_status(file_name_stored, new_status):
    execute_sql("UPDATE files SET file_status = '{}' WHERE file_name_stored = '{}'".format(
        new_status, file_name_stored))

# Starts the transcription process to the files with the given payment_id, payment_status="paid" and file_status="pending"


def start_transcriptions(client_secret):
    files = execute_sql("SELECT file_name_stored FROM files WHERE payment_id = '{}' AND payment_status = 'paid' AND file_status = 'pending'".format(
        client_secret), fetch=True)
    for file in files:
        file_name_stored = file[0]
        update_file_status(file_name_stored, "processing")
        job_response = transcribe_file(file_name_stored)
        if job_response['HTTPStatusCode'] != 200:
            update_file_status(file_name_stored, "error")
            print("Error in job response:")
            print(job_response)


# Transcribes a file and returns the job response
def transcribe_file(file_name_stored):
    # Get the credentials from the instance metadata service
    r = requests.get(AWS_CREDENTIALS_ADDRESS)
    credentials = json.loads(r.text)

    # Gets AWS Batch client
    batch = boto3.client('batch',
                         region_name=AWS_REGION,
                         aws_access_key_id=credentials['AccessKeyId'],
                         aws_secret_access_key=credentials['SecretAccessKey'], aws_session_token=credentials['Token'])

    job_response = batch.submit_job(
        jobName='platic-whisper',
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
        }
    )

    return job_response
