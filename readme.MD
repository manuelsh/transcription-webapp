# A webapp for transcribing audio files

In this repo you will find the elements to build a webapp for performing transcription of files. The webapp includes authetication of users, payment, handling of files and automatic transcription using state of the art models.

It is composed by the different elements needed in the frontend (for files uploading, payment, reviewing and downloading transcriptions, authenticate users, and more) and the elements of the backend; mostly an API and a few docker containers.

The stack used is the following:

1. API: mostly built using Python FastApi
2. Serving: GUnicorn and Nginx
3. SSL certificate: Certbot
4. Containers with Docker Compose
5. Database: SQLite, would need to be scaled to a better solution
6. Frontend elements: HTML, CSS, Javascript and materialize framework
7. Payment: Stripe
8. AWS S3: mostly Batch Jobs and ec2
9. ML model uses Whisper from OpenAI, downloaded from HuggingFace
10. User authentication: Firebase

## Overall mechanics and elements in this repo

The frontend are a few elements made in html, CSS and javascript, that need to be added to the website (you can find them in `/website_elements` folder), and the backend is the API that is deployed in a server, with GUnicorn and Nginx.

The different elements of the webapp interact in the following way:

1. First, a user authenticates, using the frontend elements in the file `sign-in.html`. User can be redirected to a website to start uploading files to be transcribed.
2. With the frontend upload element, the user uploads the files to be transcribed and clicks on the button to checkout. The files are stored in an S3 bucket. This uses the element `file_upload_element.html` and the API endpoint `/uploadfile` and `/getfilestopay`.
3. If the user has free seconds (so that she can test the transcription) larger than the files total length, the files will be set to transcribe for free. Otherwise, the user will be redirected to the checkout page to pay the difference.
4. The checkout element opens the checkout page so that the user can pay. It uses Stripe. It shows the files that are ready to be transcribed, the total price and the credit card payment element. This uses the element `checkout_payment_element.html` and the API endpoint `/getfilestopay` and `createpaymentintent`. Note that there is a minimum payment set in the env file.
5. Once the payment is done, the API has a Stripe webhook that receives the information that a user has paid. The user will be redirected to the page that shows the files that are ready to be transcribed and the ones transcribed already. This uses the element `show_files_element.html` and the API endpoint `/get-files`.
6. In the server, with the files that are paid and ready to be transcribed, a batch job will be initiated using AWS Batch. This will transcribe the files and store them in the S3 bucket. The resulting files will be stored with the same name as the original file, but with the suffix `_result.json`. The batch job uses the container that is in the `whisper-container` folder.
7. Once the file is transcribed and email is sent to the user informing her that the transcription is available.
8. The user will see the file with the element `show_files_element.html` and the API endpoint `/get-files`. He will be able to download the files and rate them.

## Running the server

To run the production server (this was done in an ec2 machine), inside the folder run:

`sudo docker-compose  --env-file .env.prod -f docker-compose.prod.yml up -d --build`

For the development server, run:

`sudo docker-compose --env-file .env.dev -f docker-compose.dev.yml up -d --build`

It important to run it with `sudo` as it needs to have root access to the certificates folderss.

Once the server is running, you can test it with for example by:

`curl https://api.yourwebsite.com/docs`

or browsing it there, which should return the FastAPI swagger documentation.

Note that you need to setup your URL so that the subdomain `api` redirects to your ec2 machine serving the model.

## Stopping

To stop the server, run:

`sudo docker-compose -f docker-compose.prod.yml down`

## Logs

To see the logs of the containers, run:

`sudo docker-compose --env-file .env.prod -f docker-compose.prod.yml logs -f`

and for development environment, run:

`sudo docker-compose --env-file .env.dev -f docker-compose.dev.yml logs -f`

## Setting up AWS and webhosting

### Webhosting

In your web host, you should redirect the subdomain `api` to the static IP of the ec2 machine. Usually this is done with type `A`.

### ec2 server

On ec2 one needs to setup a machine which hosts the API. You will need also:

- a static IP
- security groups opening the ports 443, 80 and 8000

### S3

S3 bucket is set up to store the files that are uploaded by the users and the result of the transcription. The bucket is called `platic-files` and it is set up so that it can be accessed only from the server.

### Policies

We use the policy `platic-files-bucket-access` to allow the server to access the S3 bucket (needs to be associated to the IAM role of the server, see next point).

The policy is called `platic-files-bucket-access` and it is in the file `aws/policies/platic-files-bucket-access.json`.

### IAM Role

There is an IAM role that needs to be added to the ec2 machine so that it can access the S3 bucket and also that is used for the Batch jobs. The role is called `ec2-access-s3-platic-files`, and it should have the following policies:

- `AmazonEC2ContainerServiceforEC2Role`, so that the ec2 machine can access the docker containers in the Batch jobs.
- `platic-files-bucket-access`

### Batch

The Batch job is set up to run the container in the `whisper-container` folder, which pulls it from docker hub. For the batch job one needs to configure the four elements:

1. Compute environment
2. Job queue
3. Job

Number 1 and 2 are done in the AWS Batch console, number 3 is done in a Notebook, and number 4 is done programmatically.

## Whisper container

The Whisper container is in the folder `whisper-container`. It is a docker container that is used in the Batch job to transcribe the files. It contains the model that does the transcription.

There is a readme.MD in the folder that explains its mechanics.

The container should be serve in dockerhub.

## Configuration (also to use in a new project)

Currently, it is set up to run with the host `api.platic.io`, but one can set it up to other URL by mainly adjusting the nginx configuration and the certbot.

### Environment variables

The environment variables are set in the file `.env.prod` or in the `.env.dev` files. The variables are:

- `USERS_FILES_PATH`: path to the folder where the user files are stored.
- `DATABASE_PATH`: path to the folder where the database is stored.
- `DATABASE_FILE_NAME`: name of the database file.
- `PRICE_PER_MINUTE`: price per minute of transcription.
- `NEW_USER_FREE_MINUTES`: free minutes for new users.
- `MINIMUM_PAYMENT`: minimum payment for checkout with Stripe.
- `STRIPE_API_KEY`: Stripe API key.
- `STRIPE_WEBHOOK_SECRET`: Stripe webhook secret.
- `S3_BUCKET`: S3 bucket name.
- `AWS_CREDENTIALS_ADDRESS`: address of the AWS credentials file associated with the ec2 machine,
- `AWS_REGION`: AWS region.
- `JOB_QUEUE`: AWS Batch job queue name.
- `JOB_DEFINITION`: AWS Batch job definition name.
- `FROM_EMAIL`: The email where the finish transcription email will be sent from.
- `EMAIL_PASSWORD`: the email with the password.

As an example, see bellow how the file will look like:

```
# User files and database paths
USERS_FILES_PATH="/home/platic-users-files"
DATABASE_PATH="/home/platic-database"
DATABASE_FILE_NAME="platic.db"

# API timeout, used for FastAPI and GUnicorn
API_TIMEOUT=360

# Prices and minutes
PRICE_PER_MINUTE=0.10
PRICE_PER_MINUTE_HIGH_VOLUME=0.08
VOLUME_THRESHOLD=1000
NEW_USER_FREE_MINUTES=20
MINIMUM_PAYMENT=1.00

# Stripe keys
STRIPE_API_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
STRIPE_WEBHOOK_SECRET="xxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# AWS credentials and info
AWS_CREDENTIALS_ADDRESS="http://......."
S3_BUCKET="platic-files"
AWS_REGION="eu-west-1"
JOB_QUEUE="platic-job-queue"
JOB_DEFINITION="platic-job-definition"

# Email credentials
FROM_EMAIL="info@platic.io"
EMAIL_PASSWORD=""xxxxxxxxxxxxxxxxxxxxxxxxxxxx"

```

### Database and users info

Users files are stored in the folder defined in the variable `USERS_FILES_PATH`, in the `.env.prod` or in the `.env.dev` files.

Current database is a sqlite database, which is stored in the folder defined in the variable `DATABASE_PATH`, and the file name is defined in the variable `DATABASE_FILE_NAME`, also in the `.env.prod` or in the `.env.dev` files.

The paths `USERS_FILES_PATH`, `DATABASE_PATH` and the file `DATABASE_FILE_NAME` needs to be created manually, also the new database. To restart the database, run the following comand:

`sudo python3 init_db.py`

### Certbot

Certbot needs to be configured outside the docker compose, in the hosting machine, so that the certificates are stored in the correct folder, which is:

`/etc/letsencrypt/live/api.platic.io/`

Certbot is configured to renew the certificates automatically, so it is not necessary to do anything else.

Note that the Certbot docker will create the folder `data/certbot` in the project, which is a volume to store the certificates, and the file `init-letsencrypt.sh` which is a script to initialize the certificates.

### Nginx

The nginx configuration is in the file `nginx-prod.conf`, in the folder `nginx`, it sets up the folder of the certificates and the host (in this case `api.platic.io`). It also sets up the proxy to the FastAPI server, in port 8000.

### Docker Compose

Docker compose confiuration is in the file `docker-compose.prod.yml`, it sets up the different containers and their network.

The docker compose configuration file also sets the ports to be used, in this case 443 for https and 80 for http. The internal port 8000 is used to connect to the FastAPI API.

Docker compose reads the environment variables from the fil `.env.prod`, which is not in the repository, which is in the form `VARIABLE=VALUE`.

### FastAPI

FastAPI is set up in the file `transcript-fastapi/main.py`, which is the entry point of the application.

Note that it has the CORS middleware, which allows to connect to the API from other domains.

### GUnicorn

GUnicorn is set up in the file `transcript-fastapi/gunicorn_conf.py`.

It's binded to the port 8000, which is the internal port of the FastAPI API. It uses the number of cores of the machine to set the number of workers plus one.s

Note that it has a timeout, which can be adjusted if needed.

## Description of frontend and API

### Frontend: Website elements

The frontend is based on a few frontend elements that need to be added to the website.

In the folder `website elements` you will find the html code that needs to be added to the website to make it work with the Platic API. Current website is done in Webflow, but should work with any other website. The elements are inside the html files, you will find where to start copy and pasting the code. In concrete you will find:

#### File upload element

It's in the file `file_upload_element.html`. It's a button that opens a file explorer to select one or more files. It has a function that sends the file to the Platic API to be processed and stored for doing the transcription once payment is done.

### Checkout payment element

It's in the file `checkout_payment_element.html`. Using Platic API it gets the files that needs to be paid and the total price. It has a function that opens the checkout payment page which uses Stripe. Once the payment is done, it will go to the page that shows the files that are ready to be transcribed.

### Show files element

It shows in a table the files that are ready to be transcribed or the ones transcribed.

## Platic API

The platic API is in the folder `transcript-fastapi`. It's a FastAPI application that has the following endpoints:

### Upload file (POST)

`/uploadfile/`

It receives a file and stores it in the server. It returns info on the status of the uploading and processing.

### Get files to pay (GET)

`/get_files_to_pay/{user_id}`

It receives the user id and returns the files that need to be paid and the total price.

### Clean cart (GET)

`/cleancart/{user_id}`

It receives the user id and removes all files from the cart.

### Create payment intent (POST)

`/create-payment-intent/`

It receives the user id, user email and creates a payment intent in Stripe based on the files pending to be transcribed. It returns the client secret for Stripe.

### Get files (GET)

`/get-files/{user_id}`

It receives the user id and returns the files that are ready to be transcribed or the ones that have been transcribed.

### Webhook (POST)

`/webhook`

It receives the webhook from Stripe that confirms that some files have been pais and updates the status of the files in the database to 'paid'.
