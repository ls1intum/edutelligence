from typing import cast
from sqlalchemy import Column, String, Integer, Float, ForeignKey
from sqlalchemy.orm import relationship

from athena.database import Base
from athena.text import Feedback
from athena.logger import logger


class DBTextBlock(Base):
    __tablename__ = "text_blocks"

    id = Column(String, primary_key=True, index=True)  # type: ignore
    text = Column(String)  # type: ignore
    index_start = Column(Integer)  # type: ignore
    index_end = Column(Integer)  # type: ignore
    position_in_cluster = Column(Integer)  # type: ignore

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
        if feedback.index_start is None or feedback.index_end is None:
            return False
        return self.index_start <= feedback.index_start and feedback.index_end <= self.index_end  # type: ignore

    def feedback_is_linked_to_block(self, feedback: Feedback) -> bool:
        """The info whether the feedback is linked to the block is stored in the metadata of the feedback."""
        return feedback.meta.get("block_id") == self.id

    def distance_to(self, other):
        """
        Returns the distance between this block and another block.
        """
        return self.cluster.distance_between_blocks(self, other)

    def calculate_added_distance(self):
        """
        Calculates the added distance of this block.
        The added distance is the sum of (1-distance) for each block in the cluster's distance matrix,
        minus 1 (because the distance between a block and itself is 1).
        """
        distance_matrix = self.cluster.distance_matrix
        block_index = self.cluster.blocks.index(self)
        if len(distance_matrix) <= block_index:
            logger.warning("Block %s is not in the distance matrix of cluster %s", self.id, self.cluster.id)
            logger.debug("Distance matrix: %s", distance_matrix)
            return 999 # Something went wrong, this block is not in the distance matrix
        distance_matrix_row = distance_matrix[block_index]
        # subtract 1 because the statement also included the distance to itself, but it shouldn't be included
        return sum(1 - distance for distance in distance_matrix_row) - 1

    def __str__(self):
        return f"TextBlock{{id={self.id}, submission_id={self.submission_id} text='{self.text}', index_start='{self.index_end}', index_end='{self.index_end}', cluster_id='{self.cluster_id}'}}"
