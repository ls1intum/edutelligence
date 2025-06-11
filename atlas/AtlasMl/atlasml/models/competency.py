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
    # id
    title: str
    description: str
    taxonomy: CompetencyTaxonomy


class CompetencyRelationType(str, Enum):  # TOBE DETERMINED LATER
    SUPERSET = "SUPERSET"
    SUBSET = "SUBSET"


class CompetencyRelation(BaseModel):
    tail_competency_id: str
    head_competency_id: str
    relation_type: CompetencyRelationType


class GenerateCompetencyRequest(BaseModel):
    id: str
    description: str


class GenerateCompetencyRequestBatch(BaseModel):
    competencies: list[GenerateCompetencyRequest]


class GenerateCompetencyResponse(BaseModel):
    competencies: list[Competency]
    competency_relations: list[CompetencyRelation]


class GenerateEmbeddingsResponse(BaseModel):
    embeddings: list


class SuggestCompetencyRequest(BaseModel):
    id: str
    description: str


class SuggestCompetencyResponse(BaseModel):
    competencies: list[Competency]
    competency_relations: list[CompetencyRelation]


class SaveCompetencyRequest(BaseModel):
    id: str
    description: str
    competencies: list[Competency]
    competency_relations: list[CompetencyRelation]


class SaveCompetencyResponse(BaseModel):
    competencies: list[Competency]
    competency_relations: list[CompetencyRelation]
