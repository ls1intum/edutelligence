from sqlalchemy import Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import relationship

from athena.database import Base


class DBStructuredGradingInstruction(Base):
    __tablename__ = "structured_grading_instructions"

    id = Column(Integer, primary_key=True, index=True)
    feedback_credits = Column(Float, nullable=False)
    feedback_description = Column(String, nullable=False)
    grading_outcome = Column(String, nullable=False)
    usage_description = Column(String, nullable=False)
    usage_limit = Column(Integer, nullable=False)

    criterion_id = Column(Integer, ForeignKey("structured_grading_criterions.id", ondelete="CASCADE"), index=True)

    structured_grading_criterion = relationship("DBStructuredGradingCriterion", back_populates="structured_grading_instructions")
