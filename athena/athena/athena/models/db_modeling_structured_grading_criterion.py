from athena.models.db_structured_grading_instruction import DBStructuredGradingInstruction

from athena.database import Base

class DBModelingStructuredGradingCriterion(DBStructuredGradingInstruction, Base):
    __tablename__ = "modeling_structured_grading_criteria"