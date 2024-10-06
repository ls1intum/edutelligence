from git import Repo

class GenerateFileSummaryInput:
    """
    DTO class for generating file summaries, containing repository details.
    """
    template_repo: Repo
    submission_repo: Repo
    exercise_id: int
    submission_id: int

    def __init__(self, template_repo: Repo, submission_repo: Repo, exercise_id: int, submission_id: int):
        self.template_repo = template_repo
        self.submission_repo = submission_repo
        self.exercise_id = exercise_id
        self.submission_id = submission_id