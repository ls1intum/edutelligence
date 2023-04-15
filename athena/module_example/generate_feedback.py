from athena.models import Exercise, Submission, Feedback
from athena.feedback import receives_feedback
from athena.storage import get_stored_submissions
from athena.suggestion import provide_suggestion

def is_in_same_cluster(submission1: Submission, submission2: Submission) -> bool:
    return submission1.meta.get("cluster") == submission2.meta.get("cluster")

@generates_feedback
def suggest_feedback(exercise: Exercise, submission: Submission):
    print(f"suggest_feedback: Received submission {submission.id} of exercise {exercise.id}.")
    return 
