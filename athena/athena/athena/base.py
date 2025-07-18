"""
SQLAlchemy declarative base for all database models.
This file exists to avoid circular imports between models and schemas.
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()
