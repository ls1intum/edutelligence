from athena.feedback import Feedback, on_feedback
from athena.storage import get_submissions
from athena.suggestion import provide_suggestion

@on_feedback(new_only=True) # Alternatives: on_feedback(), on_feedback(update_only=False)
def process_feedback(feedback: Feedback):
    # find similar submissions
    for submission in get_submissions(feedback.exercise_id):
        if submission.student_id == feedback.student_id:
            continue
        if is_in_same_cluster(submission, feedback.submission):
            # reuse feedback
            adjusted_feedback = feedback.copy(submission=submission)
            provide_suggestion(adjusted_feedback)
