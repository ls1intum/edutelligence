from typing import List

from athena import Exercise, Submission, submissions_consumer
from athena.storage import store_submission


def determine_cluster(submission: Submission) -> str:
    return "cluster1"


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    print(f"Received {len(submissions)} submissions for exercise {exercise.id}")
    for submission in submissions:
        submission.meta["cluster"] = determine_cluster(submission)
        store_submission(submission)