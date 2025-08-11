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
    course_id: str


class ExerciseWithCompetencies(BaseModel):
    id: str
    title: str
    description: str
    competencies: list[str]
    course_id: str

class ClusterCenters(BaseModel):
    cluster_id: str
    course_id: str
    vector_embedding: list[float]

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
    course_id: str


class SuggestCompetencyResponse(BaseModel):
    competencies: list[Competency]


class SaveCompetencyRequest(BaseModel):
    competency: Optional[Competency] = None
    exercise: Optional[ExerciseWithCompetencies] = None
    operation_type: OperationType
