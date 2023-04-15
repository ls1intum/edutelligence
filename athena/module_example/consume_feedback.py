from athena import Exercise, Submission, Feedback, feedback_consumer
from athena.storage import get_stored_submissions, store_feedback_suggestion

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
