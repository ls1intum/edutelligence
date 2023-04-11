from athena.submission import Exercise, Submission, on_submission, on_exercise_deadline
from athena.storage import store_submission
from .clustering import determine_cluster

@on_submission(new_only=True) # Alternatives: on_submission(), on_submission(update_only=False)
def process_submission(submission: Submission):
    # determine cluster
    submission.meta.cluster = determine_cluster(submission)
    store_submission(submission)


@on_exercise_deadline
def process_exercise_deadline(exercise: Exercise):
    ...
    