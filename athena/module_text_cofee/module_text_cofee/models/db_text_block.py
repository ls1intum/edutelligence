from sqlalchemy import Column, String, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship

from athena.database import Base
from athena.text import Feedback


class DBTextBlock(Base):
    __tablename__ = "text_blocks"

    id = Column(String, primary_key=True, index=True)
    text = Column(String)
    start_index = Column(Integer)
    end_index = Column(Integer)
    added_distance = Column(Float, nullable=True, default=None)

    # foreign keys
    submission_id = Column(Integer, ForeignKey("text_submissions.id"))  # FK to athena-native table
    cluster_id = Column(Integer, ForeignKey("text_clusters.id"))  # FK to custom table

    submission = relationship("DBTextSubmission")
    cluster = relationship("DBTextCluster", back_populates="blocks")

    def includes_feedback(self, feedback: Feedback) -> bool:
        """
        Whether the given feedback is included in this block.
        Example:
        - The submission is "Hello world! This is a test.".
        - The text block within that submission is "This is a test." (index 13 to 27).
        - The feedback is given on "test" (index 22 to 26). => True
        - The feedback is given on "This is a test." (index 13 to 27). => True
        - The feedback is given on "Hello world!" (index 0 to 12). => False

        This is used to match feedbacks to text blocks, even if the feedback is not given on the exact text block.
        """
        return self.start_index <= feedback.get_start_index() and feedback.get_end_index() <= self.end_index

    def feedback_is_linked_to_block(self, feedback: Feedback) -> bool:
        """The info whether the feedback is linked to the block is stored in the metadata of the feedback."""
        return feedback.meta.get("block_id") == self.id

    def distance_to(self, other):
        """
        Returns the distance between this block and another block.
        """
        return self.cluster.distance_between_blocks(self, other)

    def __str__(self):
        return f"TextBlock{{id={self.id}, submission_id={self.submission_id} text='{self.text}', start_index='{self.start_index}', end_index='{self.end_index}', added_distance='{self.added_distance}', cluster_id='{self.cluster_id}'}}"
