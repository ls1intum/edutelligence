from sqlalchemy import Column, Integer, String, JSON, ForeignKey

from .model import Model


class DBSubmission(Model):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    exercise_id = Column(Integer, ForeignKey("exercises.id", ondelete="CASCADE"), index=True)
    feedback_id = Column(Integer, ForeignKey("feedbacks.id"), index=True)
    content = Column(String)
    student_id = Column(Integer, index=True)

    meta = Column(JSON)
