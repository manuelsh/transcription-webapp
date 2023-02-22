# Gunicorn Configuration File
# From https://www.vultr.com/docs/how-to-deploy-fastapi-applications-with-gunicorn-and-nginx-on-ubuntu-20-04/

from multiprocessing import cpu_count

# Socket Path
bind = ['0.0.0.0:8000']

# Worker Options
workers = cpu_count() + 1
worker_class = 'uvicorn.workers.UvicornWorker'
timeout = 240 # in case we need to receive answer from bananatag

# Logging Options
loglevel = 'debug'
accesslog = './access_logs'
errorlog =  './error_logs'
