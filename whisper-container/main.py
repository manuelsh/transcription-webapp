# Takes file from S3, transcribes it,
# and returns transcription to S3

import requests
import json
import boto3
import os
import whisper
from config import *

# Gets S3 client


def get_s3_client(credentials_http_path):
    r = requests.get(credentials_http_path)
    credentials = json.loads(r.text)
    return boto3.client('s3',
                        aws_access_key_id=credentials['AccessKeyId'],
                        aws_secret_access_key=credentials['SecretAccessKey'],
                        aws_session_token=credentials['Token'])

# Transcribe expects:
# - 'file': a flac file with 16,000 hertz sample rate
# - 'language': a string with the language code for whisper, if 'auto',
#               it will auto detect by setting the language to None
# - 'task': either 'transcribe' or 'translate'. If 'translate', it will translate to English.


def transcribe(model_type, file_name, language, task):
    model = whisper.load_model(model_type)
    transcription = model.transcribe(file_name,
                                     language=language,
                                     task=task)
    return transcription


def stores_dict_in_json_file(dictionary, file_name):
    result_json = json.dumps(dictionary)
    with open(file_name, 'w') as f:
        f.write(result_json)


if __name__ == "__main__":
    print('Starting transcribing')
    # Gets S3 client
    s3 = get_s3_client(S3_CREDENTIALS_PATH)

    # Download file from the bucket
    file_name = os.environ['FILE_NAME']
    s3.download_file(S3_BUCKET,
                     file_name,
                     file_name)
    print('Downloaded file from S3: {}'.format(file_name))

    # Transcribes file
    if os.environ['LANGUAGE'].lower() == 'auto':
        language = None
    else:
        language = os.environ['LANGUAGE']

    result = transcribe(WHISPER_MODEL,
                        file_name,
                        language,
                        os.environ['TASK'])
    print('Transcribed file: {}'.format(file_name))

    # Stored dict in json file
    json_file_name = file_name+'_result.json'
    stores_dict_in_json_file(result, json_file_name)
    print('Stored result in json file: {}'.format(json_file_name))

    # Uploads json file to S3
    s3.upload_file(json_file_name,
                   S3_BUCKET,
                   json_file_name)
    print('Uploaded json file to S3: {}'.format(json_file_name))

    # Sends a POST request to the status file address to indicate
    # that the transcription is finished successful
    status_file_address = STATUS_FILE_ADDRESS
    data = {'file_name_stored': file_name,
            'new_file_status': 'processed'}
    result = requests.post(status_file_address, json=data)
    print('Sent POST request to status file address: {}'.format(
        status_file_address), flush=True)
    print('Result: {}'.format(result.text), flush=True)
