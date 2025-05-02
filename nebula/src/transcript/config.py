import os

class Config:
    VIDEO_STORAGE_PATH = os.getenv("VIDEO_STORAGE_PATH", "./temp")
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Ensure the directory exists after class is defined
os.makedirs(Config.VIDEO_STORAGE_PATH, exist_ok=True)
