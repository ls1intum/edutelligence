from sqlalchemy import Column, Integer, JSON
from .model import Model


class DBSubmission(Model):
    id = Column(Integer, primary_key=True, index=True, nullable=False)
    meta = Column(JSON, nullable=False)
