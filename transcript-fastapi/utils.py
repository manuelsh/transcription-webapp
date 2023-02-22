from io import BytesIO
import os
import pydub
import base64
import banana_dev as banana
import tempfile
import uuid
import sqlite3

# Database file model
# Latest update: 2023-02-14
# Columns:
# - user_id: the user's id, coming form firebase
# - file_name_stored: the file's name stored in the server
# - file_name: the original file's name
# - file_length: the length of the file in seconds
# - file_status: the status of the file, can be 'pending', 'processing', 'processed', 'error'
# - payment_status: the status of the payment, can be 'pending', 'paid'
# - payment_id: the id of the payment, coming from stripe (client_secret)

# Main variables
USERS_FILES_PATH=os.environ["USERS_FILES_PATH"]+"/"
DATABASE_PATH=os.environ["DATABASE_PATH"]+"/"
DATABASE_FILE_NAME=os.environ["DATABASE_FILE_NAME"]
PRICE_PER_MINUTE=os.environ["PRICE_PER_MINUTE"]

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
            return (True, temp_file, file_info )
    except:
        return (False, None, None)

# converts file to flac, 16000Hz, mono    
def converts_file(file):
    audio_file = pydub.AudioSegment.from_file(file.name).set_frame_rate(16000).set_channels(1)
    return audio_file
    
# takes an "audiosegment" object, stores file in folder with unique name, and returns new file name
def stores_file(audio_file, user_id):
    file_name = user_id + "_" + str(uuid.uuid4()) + ".flac"
    audio_file.export(USERS_FILES_PATH + file_name, format="flac")
    return file_name
    
def records_file_in_db(file_id, file_name, user_id, file_length):
    # records file name, user_id and status=pending in database
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?)", (user_id, file_id, file_name, file_length, "pending", "pending","pending"))    
    conn.commit()
    conn.close()

def checks_file_duplicated(file_name, user_id, file_length):
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute("SELECT file_name FROM files WHERE user_id = ? AND file_name = ? AND file_length = ? AND payment_status = 'pending'", (user_id, file_name, file_length))
    duplicated_file_info = cur.fetchone()
    conn.close()
    if duplicated_file_info:
        return (True, duplicated_file_info)
    else:
        return (False, None)

# Processes uploaded file: checks it, converts it, and stores the information in the database
def file_processor(file,user_id):
    status, temp_file, file_info = is_media_file(file.file)

    if status:
        file_duplicated, duplicated_file_info = checks_file_duplicated(file.filename, 
                                                                        user_id, 
                                                                        file_info['duration'])
    
        if not file_duplicated:
            file_converted = converts_file(temp_file)
            file_id = stores_file(file_converted, user_id)
            records_file_in_db(file_id, file.filename, user_id, file_info['duration'])
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
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute("SELECT file_name, file_length, file_name_stored FROM files WHERE user_id = ? AND payment_status = 'pending'", (user_id,))
    files = cur.fetchall()
    conn.close()
    
    # Puts data in a dictionary, file by file
    files = [{"file_name": file[0], 
              "file_length": file[1], 
              "file_name_stored": file[2],
               "file_price":round(file[1]/60.* float(PRICE_PER_MINUTE), 2) } for file in files]
    
    total_price = round( sum([file["file_price"] for file in files]), 2)
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
        cur.execute("UPDATE files SET payment_id = ? WHERE user_id = ? AND file_name_stored = ? AND payment_status = 'pending'", (payment_id, user_id, file["file_name_stored"]))
    conn.commit()
    conn.close()


# Changes a set of files with given payment_id to "paid" status
def change_files_status_to_paid(payment_id):
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE files SET payment_status = 'paid' WHERE payment_id = ?", (payment_id,))
    conn.commit()
    conn.close()

# Removes payment id to a set of files, and change it to some text
def remove_payment_id(payment_id, text):
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE files SET payment_id = ? WHERE payment_id = ?", (text, payment_id))
    conn.commit()
    conn.close()


# Removes all files from user cart
# It will change the status of the files to "cancelled" and the payment status to "cancelled"
# Will also remove the files from the server
def remove_all_files_from_cart(user_id):
    try:
        # Gets all pending payment files from a user id
        conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
        cur = conn.cursor()
        cur.execute("SELECT file_name_stored FROM files WHERE user_id = ? AND payment_status = 'pending'", (user_id,))
        files = cur.fetchall()
        conn.close()
        
        # Removes files from server
        for file in files:
            os.remove(USERS_FILES_PATH + file[0])
        
        # Changes status of files to "cancelled" and payment status to "cancelled"
        conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
        cur = conn.cursor()
        cur.execute("UPDATE files SET payment_status = 'cancelled', file_status = 'cancelled' WHERE user_id = ? AND payment_status = 'pending'", (user_id,))
        conn.commit()
        conn.close()
        
        return {'status': True}
    
    # Returns false and error message if something goes wrong
    except Exception as e:
        return {'status': False, 'error_message': str(e)}


# Get the files of a user to show the status and be able to donwload them
# Returns a list of dictionaries with the file name, the file length, 
# the file status and the payment status
def get_files_info(user_id):
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    cur = conn.cursor()
    cur.execute("SELECT file_name, file_length, file_status, payment_status FROM files WHERE user_id = ?", (user_id,))
    files = cur.fetchall()
    conn.close()
    
    files = [{"file_name": file[0], 
              "file_length": file[1], 
              "file_status": file[2], 
              "payment_status": file[3]} for file in files]
    
    return files




#### BELOW: DEPRECATED ####
# Expects an mp3 file named test.mp3 in directory
def async transcribe(file):
    #mp3bytes = BytesIO(file)
    #mp3 = base64.b64encode(mp3bytes.getvalue()).decode("ISO-8859-1")
    mp3 = base64.b64encode(file).decode("ISO-8859-1")
    model_payload = {"mp3BytesString": mp3}
    out = banana.run(os.environ["BANANA_API_KEY"],
                    os.environ["BANANA_MODEL_KEY"], 
                    model_payload)
    return out['modelOutputs'][0]