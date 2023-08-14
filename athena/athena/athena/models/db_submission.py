from sqlalchemy import Column, BigInteger, JSON
from .model import Model


class DBSubmission(Model):
    id = Column(BigInteger, primary_key=True, index=True, nullable=False)
    meta = Column(JSON, nullable=False)
