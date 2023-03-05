# Runs during container build time to get model weights 
from config import *
import whisper
import os

def download_model():
    model = whisper.load_model(WHISPER_MODEL)

if __name__ == "__main__":
    download_model()