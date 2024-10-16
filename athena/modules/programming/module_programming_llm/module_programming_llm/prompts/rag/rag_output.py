from typing import Sequence

from pydantic import BaseModel, Field


class RAGOutput(BaseModel):
    """Collection of feedbacks making up an assessment for a file"""
    rag_queries: Sequence[str] = Field(description="A sequence of search queries for a RAG web-search provider", default=[])
