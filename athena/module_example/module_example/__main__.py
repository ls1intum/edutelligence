from typing import List

from athena import *
from athena.storage import *


def is_in_same_cluster(submission1: Submission, submission2: Submission) -> bool:
    return submission1.meta.get("cluster") == submission2.meta.get("cluster")

@feedback_consumer
def process_incoming_feedback(exercise: Exercise, submission: Submission, feedback: Feedback):
    print(f"process_feedback: Received feedback for submission {submission.id} of exercise {exercise.id}.")
    # find similar submissions
    for submission in get_stored_submissions(feedback.exercise_id):
        if submission.student_id == feedback.student_id:
            continue
        if is_in_same_cluster(submission, feedback.submission):
            # reuse feedback
            adjusted_feedback = feedback.copy(submission=submission)
            store_feedback_suggestion(adjusted_feedback)


def determine_cluster(submission: Submission) -> str:
    return "cluster1"


@submissions_consumer
def receive_submissions(exercise: Exercise, submissions: List[Submission]):
    print(f"Received {len(submissions)} submissions for exercise {exercise.id}")
    for submission in submissions:
        submission.meta["cluster"] = determine_cluster(submission)
        store_submission(submission)


@feedback_provider
def suggest_feedback(exercise: Exercise, submission: Submission) -> Feedback:
    print(f"suggest_feedback: Received submission {submission.id} of exercise {exercise.id}.")
    return


if __name__ == "__main__":
    app.start(port=5001)