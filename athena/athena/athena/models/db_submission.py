from sqlalchemy import Column, Integer, JSON
from .model import Model


class DBSubmission(Model):
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, index=True)
    meta = Column(JSON)
