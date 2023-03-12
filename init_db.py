import os
import dotenv
import sqlite3
import uuid

print('''WARNING: This script will delete the database and create a new one.
 If you want to delete the database and initiate it, type DELETE.''')
answer = input('Type DELETE to continue: ')

if answer == 'DELETE':

    # Read variables DATABASE_PATH and DATABASE_FILE_NAME from `env.prod` file

    dotenv.load_dotenv(dotenv_path='.env.prod')

    DATABASE_PATH = os.environ['DATABASE_PATH'] + '/'
    DATABASE_FILE_NAME = os.environ['DATABASE_FILE_NAME']

    # Check if database file exist and if so
    # backup the database file with a new unique name based on uuid
    if os.path.exists(DATABASE_PATH + DATABASE_FILE_NAME):
        new_name = str(uuid.uuid4()) + '.db'
        os.rename(DATABASE_PATH + DATABASE_FILE_NAME, DATABASE_PATH + new_name)
        print('Database file backed up to ' + new_name)

    # Initiating the database connection
    conn = sqlite3.connect(DATABASE_PATH + DATABASE_FILE_NAME)
    c = conn.cursor()

    # Create the files table with the following columns:
    # - user_id: the user's id, coming form firebase
    # - file_name_stored: the file's name stored in the server
    # - file_name: the original file's name
    # - file_length: the length of the file in seconds
    # - file_status: the status of the file, can be 'pending', 'processing', 'processed', 'error'
    # - payment_status: the status of the payment, can be 'pending', 'paid', 'error', 'free' or 'canceled'
    # - payment_id: the id of the payment, coming from stripe (client_secret), can be null

    c.execute('''CREATE TABLE files
                    (user_id text, file_name_stored text, file_name text, file_length numeric , file_status text, payment_status text, payment_id text)''')

    print('Files table initiated')

    # Create the users table with the following columns:
    # - user_id: the user's id, coming form firebase
    # - user_email: the user's email
    # - user_seconds: the amount of seconds the user has available to process files
    # - spending: the amount of money the user has spent

    c.execute('''CREATE TABLE users
                    (user_id text, user_email text, user_seconds numeric, spending numeric)''')

    print('Users table initiated')

else:
    print('Database not initiated')
