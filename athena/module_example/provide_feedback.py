from athena import Exercise, Submission, Feedback, feedback_provider
from athena.storage import get_stored_submissions

def is_in_same_cluster(submission1: Submission, submission2: Submission) -> bool:
    return submission1.meta.get("cluster") == submission2.meta.get("cluster")

@feedback_provider
def suggest_feedback(exercise: Exercise, submission: Submission) -> Feedback:
    print(f"suggest_feedback: Received submission {submission.id} of exercise {exercise.id}.")
    return 
