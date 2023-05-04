from sqlalchemy import Column, Integer, String, JSON, ForeignKey

from .model import Model
from athena.database import Base


class DBSubmission(Model, Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String)
    student_id = Column(Integer, index=True)
    meta = Column(JSON)

    exercise_id = Column(Integer, ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
