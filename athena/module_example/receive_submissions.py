from typing import List

from athena.models import Exercise, Submission
from athena.submission import on_exercise_deadline
from athena.storage import store_submission


def determine_cluster(submission: Submission) -> str:
    return "cluster1"


@on_exercise_deadline
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    print(f"Received {len(submissions)} submissions for exercise {exercise.id}")
    for submission in submissions:
        submission.meta["cluster"] = determine_cluster(submission)
        store_submission(submission)