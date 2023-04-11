from athena.models import Submission, Feedback
from athena.feedback import on_feedback
from athena.storage import get_stored_submissions
from athena.suggestion import provide_suggestion

def is_in_same_cluster(submission1: Submission, submission2: Submission) -> bool:
    return submission1.meta.get("cluster") == submission2.meta.get("cluster")

@on_feedback(new_only=True) # Alternatives: on_feedback(), on_feedback(update_only=False)
def process_feedback(feedback: Feedback):
    # find similar submissions
    for submission in get_stored_submissions(feedback.exercise_id):
        if submission.student_id == feedback.student_id:
            continue
        if is_in_same_cluster(submission, feedback.submission):
            # reuse feedback
            adjusted_feedback = feedback.copy(submission=submission)
            provide_suggestion(adjusted_feedback)
