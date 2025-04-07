from pydantic import BaseModel 
from typing import List
from enum import Enum
from fastapi.responses import JSONResponse

class GenerateCompetencyRequest(BaseModel):
    description: str

class CompetencyTaxonomy(str, Enum):
    REMEMBER = "R"
    UNDERSTAND = "U"
    APPLY = "Y"
    ANALYZE = "A"
    EVALUATE = "E"
    CREATE = "C"

class Competency(BaseModel):
    title: str
    description: str
    taxonomy: CompetencyTaxonomy


class GenerateCompetencyResponse(BaseModel):
    competencies: List[Competency]