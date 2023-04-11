from athena.submission import Submission, on_submission
from athena.storage import store_submission

@on_submission(new_only=True) # Alternatives: on_submission(), on_submission(update_only=False)
def process_submission(submission: Submission):
    # determine cluster
    submission.meta.cluster = determine_cluster(submission)
    store_submission(submission)
