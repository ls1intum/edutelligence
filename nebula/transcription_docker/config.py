import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
    VIDEO_STORAGE_PATH = "/tmp"
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
