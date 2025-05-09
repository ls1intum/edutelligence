from pydantic import BaseModel 
from typing import List
from enum import Enum
from fastapi.responses import JSONResponse


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
    
class CompetencyRelationType(str, Enum): #TOBE DETERMINED LATER
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
    competencies: List[GenerateCompetencyRequest]

class GenerateCompetencyResponse(BaseModel):
    competencies: List[Competency]
    competency_relations: List[CompetencyRelation]

class GenerateEmbedingsResponse(BaseModel):
    embedings: List
