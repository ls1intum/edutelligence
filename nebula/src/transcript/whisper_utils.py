import whisper, logging
from whisper import torch
from config import Config

def transcribe_with_local_whisper(audio_path):
    logging.info("Using Whisper...")
    model = whisper.load_model(Config.WHISPER_MODEL)
    if torch.cuda.is_available():
        logging.info("Using GPU.")
        model = model.to("cuda")
    else:
        logging.info("Using CPU.")
    return model.transcribe(audio_path)
