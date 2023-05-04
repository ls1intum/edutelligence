from sqlalchemy import Column, Integer, String, JSON, ForeignKey

from .model import Model
from athena.database import Base


class DBSubmission(Model):
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String)
    student_id = Column(Integer, index=True)
    meta = Column(JSON)
