import pickle
from typing import List

from sqlalchemy import Column, Integer, LargeBinary, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from athena.database import Base
from module_text_cofee.models.db_text_block import DBTextBlock


class DBTextCluster(Base):
    __tablename__ = "text_clusters"

    id = Column(Integer, primary_key=True, index=True)
    probabilities = Column(LargeBinary)
    distance_matrix_binary = Column(LargeBinary, nullable=False)
    disabled = Column(Boolean, default=False)

    # Define the relationship to DBTextBlock
    blocks = relationship("DBTextBlock", back_populates="cluster")

    # Define the relationship to DBTextExercise
    exercise_id = Column(Integer, ForeignKey('text_exercises.id'))
    exercise = relationship("DBTextExercise")

    @property
    def distance_matrix(self) -> List[List[float]]:
        """Return the distance matrix as a list of lists of floats."""
        return pickle.loads(self.distance_matrix_binary)

    @distance_matrix.setter
    def distance_matrix(self, value: List[List[float]]):
        """Set the distance matrix from a list of lists of floats."""
        self.distance_matrix_binary = pickle.dumps(value)

    def distance_between_blocks(self, block1: DBTextBlock, block2: DBTextBlock) -> float:
        """Return the distance between two blocks in this cluster."""
        block1_index = self.blocks.index(block1)
        if block1_index == -1:
            raise ValueError(f"Block {block1} is not in this cluster")
        block2_index = self.blocks.index(block2)
        if block2_index == -1:
            raise ValueError(f"Block {block2} is not in this cluster")
        return self.distance_matrix[block1_index][block2_index]

    def __str__(self):
        return f"TextCluster{{id={self.id}, exercise_id={self.exercise_id}, probabilities={self.probabilities}, distance_matrix={self.distance_matrix}, disabled={self.disabled}}}"
