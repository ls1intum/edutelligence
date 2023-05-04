"""Import this to use schemas and decorators specific to text exercises."""
import os

from dotenv import load_dotenv

from .schemas import TextExercise, TextFeedback, TextSubmission

load_dotenv(".env")
module_type = os.environ["MODULE_TYPE"]
if module_type != "text":
    raise ImportError(f"Importing athena.text from a module of type {module_type}. This is probably a mistake, "
                      f"you should only import the file related to the exercise type that your module handles")

# re-export with shorter names, because the module will only use these
Exercise = TextExercise
Submission = TextSubmission
Feedback = TextFeedback

__all__ = [
    "Exercise", "Submission", "Feedback"
]
