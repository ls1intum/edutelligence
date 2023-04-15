import athena
from module_example import receive_feedback, receive_submissions

__all__ = ["receive_feedback", "receive_submissions"]
if __name__ == "__main__":
    athena.start()