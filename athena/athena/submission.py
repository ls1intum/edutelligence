from athena import _app
from .models import Submission
from .storage import store_submission

def on_submission(new_only=True, update_only=False):
    if new_only and update_only:
        raise ValueError("new_only and update_only cannot both be True")
    def decorator(func):
        @_app.post("/submission")
        def wrapper(submission: Submission):
            store_submission(submission)
            if new_only and submission.id is not None:
                return
            if update_only and submission.id is None:
                return
            func(submission)
        return wrapper
    return decorator