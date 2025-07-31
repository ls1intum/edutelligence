from enum import Enum

from pydantic import BaseModel


class CompetencyTaxonomy(str, Enum):
    REMEMBER = "R"
    UNDERSTAND = "U"
    APPLY = "Y"
    ANALYZE = "A"
    EVALUATE = "E"
    CREATE = "C"


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
    competency: Competency | None
    exercise: ExerciseWithCompetencies | None


