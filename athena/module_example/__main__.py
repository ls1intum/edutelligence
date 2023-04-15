import athena
from module_example import consume_feedback, consume_submissions, provide_feedback

__all__ = ["consume_feedback", "consume_submissions", "provide_feedback"]
if __name__ == "__main__":
    athena.start()