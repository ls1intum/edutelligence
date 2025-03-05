import pickle
from typing import List, cast

from sqlalchemy import Column, Integer, LargeBinary, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from athena.database import Base
from athena.logger import logger


class DBTextCluster(Base):
    __tablename__ = "cofee_text_clusters"

    id: int = Column(Integer, primary_key=True, index=True)  # type: ignore
    probabilities: bytes = Column(LargeBinary)  # type: ignore
    distance_matrix_binary: bytes = Column(LargeBinary, nullable=False)  # type: ignore
    disabled: bool = Column(Boolean, default=False)  # type: ignore

    # Define the relationship to DBTextBlock
    blocks = relationship("DBTextBlock", back_populates="cluster", order_by="DBTextBlock.position_in_cluster")  # type: ignore

    # Define the relationship to DBTextExercise
    exercise_id = Column(Integer, ForeignKey('text_exercises.id'))
    exercise = relationship("DBTextExercise")

    @property
    def distance_matrix(self) -> List[List[float]]:
        """Return the distance matrix as a list of lists of floats."""
        return pickle.loads(cast(bytes, self.distance_matrix_binary))

    @distance_matrix.setter
    def distance_matrix(self, value: List[List[float]]):
        """Set the distance matrix from a list of lists of floats."""
        self.distance_matrix_binary = pickle.dumps(value)

    def distance_between_blocks(self, block1, block2) -> float:
        """Return the distance between two blocks in this cluster."""
        block1_index = self.blocks.index(block1)
        if block1_index == -1:
            raise ValueError(f"Block {block1} is not in this cluster")
        block2_index = self.blocks.index(block2)
        if block2_index == -1:
            raise ValueError(f"Block {block2} is not in this cluster")
        if len(self.distance_matrix) <= block1_index:
            logger.warning("Block %s is not in the distance matrix of cluster %s", block1.id, self.id)
            return 999  # prevent the server from crashing and instead just ignore this distance
        if len(self.distance_matrix[block1_index]) <= block2_index:
            logger.warning("Block %s is not in the distance matrix of cluster %s", block2.id, self.id)
            return 999  # prevent the server from crashing and instead just ignore this distance
        return self.distance_matrix[block1_index][block2_index]

    def get_number_of_ungraded_blocks(self, ungraded_submission_ids: List[int]) -> int:
        """
        Return the number of blocks in this cluster whose submission has not been graded yet according to the given list.
        """
        return sum(1 for block in self.blocks if block.submission_id not in ungraded_submission_ids)

    def __str__(self):
        return f"TextCluster{{id={self.id}, exercise_id={self.exercise_id}, probabilities={self.probabilities}, distance_matrix={self.distance_matrix}, disabled={self.disabled}}}"
