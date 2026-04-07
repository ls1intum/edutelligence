from pydantic import BaseModel
from typing import Optional
from enum import Enum


class OperationType(str, Enum):
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class Competency(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    course_id: int


class ExerciseWithCompetencies(BaseModel):
    id: int
    title: str
    description: str
    competencies: Optional[list[int]] = None
    course_id: int

class SemanticCluster(BaseModel):
    cluster_id: str
    course_id: int
    vector_embedding: list[float]

class GenerateCompetencyRequest(BaseModel):
    id: int
    description: str


class GenerateCompetencyRequestBatch(BaseModel):
    competencies: list[GenerateCompetencyRequest]


class GenerateCompetencyResponse(BaseModel):
    competencies: list[Competency]


class GenerateEmbeddingsResponse(BaseModel):
    embeddings: list


class SuggestCompetencyRequest(BaseModel):
    description: str
    course_id: int


class SuggestCompetencyResponse(BaseModel):
    competencies: list[Competency]


class SaveCompetencyRequest(BaseModel):
    competencies: Optional[list[Competency]] = None
    exercise: Optional[ExerciseWithCompetencies] = None
    operation_type: OperationType

class RelationType(str, Enum):
    MATCH = "MATCHES"
    EXTEND = "EXTENDS"
    REQUIRES = "REQUIRES"

class CompetencyRelation(BaseModel):
    tail_id: int
    head_id: int
    relation_type: RelationType


class CompetencyRelationSuggestionResponse(BaseModel):
    relations: list[CompetencyRelation]


class MapNewCompetencyToExerciseRequest(BaseModel):
    exercise_id: int
    competency_id: int


class MapCompetencyToCompetencyRequest(BaseModel):
    source_competency_id: int
    target_competency_id: int