from pydantic import Field

from .submission import Submission


class TextSubmission(Submission):
    """Submission on a text exercise."""
    content: str = Field(example="Lorem ipsum dolor sit amet, consectetur adipiscing elit.")
