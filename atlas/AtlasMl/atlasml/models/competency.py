from pydantic import BaseModel
from typing import Optional
from enum import Enum


class OperationType(str, Enum):
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class Competency(BaseModel):
    id: str
    title: str
    description: str


class ExerciseWithCompetencies(BaseModel):
    id: str
    title: str
    description: str
    competencies: list[str]


class GenerateCompetencyRequest(BaseModel):
    id: str
    description: str


class GenerateCompetencyRequestBatch(BaseModel):
    competencies: list[GenerateCompetencyRequest]


class GenerateCompetencyResponse(BaseModel):
    competencies: list[Competency]


class GenerateEmbeddingsResponse(BaseModel):
    embeddings: list


class SuggestCompetencyRequest(BaseModel):
    description: str


class SuggestCompetencyResponse(BaseModel):
    competencies: list[Competency]

class SaveCompetencyRequest(BaseModel):
    competency: Optional[Competency] = None
    exercise: Optional[ExerciseWithCompetencies] = None
    operation_type: OperationType


