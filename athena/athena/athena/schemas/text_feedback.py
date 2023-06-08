from .feedback import Feedback


class TextFeedback(Feedback):
    """Feedback on a text exercise."""
    def get_start_index(self) -> int:
        """Helper function to get the start index of the feedback from its reference."""
        # reference is a string of the form "start_index-end_index"
        if self.reference is None:
            raise ValueError("Feedback does not have a reference.")
        return int(self.reference.split('-')[0])

    def get_end_index(self) -> int:
        """Helper function to get the end index of the feedback from its reference."""
        # reference is a string of the form "start_index-end_index"
        if self.reference is None:
            raise ValueError("Feedback does not have a reference.")
        return int(self.reference.split('-')[1])
