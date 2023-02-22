###########
# BUILDER #
###########

# pull official base image
FROM python:3.11.1 as builder

# set work directory
WORKDIR /usr/src/app

# set environment variables to see logs on screen
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1 

# install dependencies
COPY ./requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /usr/src/app/wheels -r requirements.txt


#########
# FINAL #
#########

# pull official base image
FROM python:3.11.1

# create directory for the app user
RUN mkdir -p /home/app

# create the appropriate directories
ENV HOME=/home/app
ENV APP_HOME=/home/app/web
RUN mkdir $APP_HOME
WORKDIR $APP_HOME

# install dependencies
# RUN apk update && apk add libpq
COPY --from=builder /usr/src/app/wheels /wheels
COPY --from=builder /usr/src/app/requirements.txt .
RUN pip install --no-cache /wheels/*

# install other packages.
# ffmped is needed for pydub
RUN apt-get update && apt-get install -y \
    ffmpeg \ 
    && rm -rf /var/lib/apt/lists/*

# copy project
COPY . $APP_HOME

# # create the app user
# RUN groupadd app_group 
# RUN useradd app
# RUN usermod -a -G app_group app

# # chown all the files to the app user
# RUN chown -R app:app_group $APP_HOME
# RUN chown -R app:app_group /home/platic-users-files
# RUN chown -R app:app_group /home/platic-database

# # change to the app user
# USER app