from . import Submission
from athena.models import DBProgrammingSubmission


class ProgrammingSubmission(Submission):
    """Submission on a programming exercise."""

    @staticmethod
    def get_model_class() -> type:
        return DBProgrammingSubmission
