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

class RelationType(str, Enum):
    MATCH = "MATCHES"
    EXTEND = "EXTENDS"
    REQUIRES = "REQUIRES"

class CompetencyRelation(BaseModel):
    tail_id: str
    head_id: str
    relation_type: RelationType


class CompetencyRelationSuggestionResponse(BaseModel):
    relations: list[CompetencyRelation]