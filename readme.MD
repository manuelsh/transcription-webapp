# Platic server

This serves the platic api. Stack is the following:

- API: FastApi
- Serving: GUnicorn and Nginx
- SSL certificate: Certbot
- Containers with Docker Compose

## Running

To run the production server, inside the folder run:

`sudo docker-compose  --env-file .env.prod -f docker-compose.prod.yml up -d --build`

For the development server, run:

`sudo docker-compose --env-file .env.dev -f docker-compose.dev.yml up -d --build`

It important to run it with `sudo` as it needs to have root access to the certificates folderss.

Once the server is running, you can test it with for example by:

`curl https://api.platic.io/docs`

or browsing it there, which should return the FastAPI swagger documentation.

## Logs

To see the logs of the containers, run:

`sudo docker-compose --env-file .env.prod -f docker-compose.prod.yml logs -f`

and for development environment, run:

`sudo docker-compose --env-file .env.dev -f docker-compose.dev.yml logs -f`

## Configuration (also to use in a new project)

Currently, it is set up to run with the host `api.platic.io`, but one can set it up to other URL by mainly adjusting the nginx configuration and the certbot.

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

## Stopping

To stop the server, run:

`sudo docker-compose -f docker-compose.prod.yml down`
