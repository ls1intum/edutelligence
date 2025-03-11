from typing import List

from pydantic import BaseModel, Field

from . import PipelineExecutionDTO
from .data.competency_dto import Competency, CompetencyTaxonomy


class CompetencyExtractionPipelineExecutionDTO(BaseModel):
    execution: PipelineExecutionDTO
    course_description: str = Field(alias="courseDescription")
    current_competencies: list[Competency] = Field(
        alias="currentCompetencies", default=[]
    )
    taxonomy_options: List[CompetencyTaxonomy] = Field(
        alias="taxonomyOptions", default=[]
    )
    max_n: int = Field(
        alias="maxN",
        description="Maximum number of competencies to extract from the course description",
        default=10,
    )
