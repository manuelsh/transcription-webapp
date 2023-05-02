# General library to send emails from gmail server

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

FROM_EMAIL = os.environ.get('FROM_EMAIL')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')


def send_email(receiver_email, subject, body):
    msg = MIMEMultipart()
    msg['From'] = FROM_EMAIL
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    text = msg.as_string()
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(FROM_EMAIL, EMAIL_PASSWORD)
        server.sendmail(FROM_EMAIL, receiver_email, text)
        server.quit()
        return {'status': 'success'}
    except:
        return {'status': 'error'}
