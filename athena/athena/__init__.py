from fastapi import FastAPI
import uvicorn

from .models import Exercise, Submission, Feedback

from .feedback_consumer import feedback_consumer
from .submissions_consumer import submissions_consumer
from .feedback_provider import feedback_provider

_app = FastAPI()

@_app.get("/")
def read_root():
    return {"athene": "module"}

def start():
    uvicorn.run(_app, host="127.0.0.1", port=8000)

__all__ = [
    "Exercise",
    "Submission",
    "Feedback",
    "feedback_consumer",
    "submissions_consumer",
    "feedback_provider",
    "start"
]