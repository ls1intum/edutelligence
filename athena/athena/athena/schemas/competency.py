from abc import ABC

from pydantic import Field, validator

from .schema import Schema
from .competency_taxonomy import CompetencyTaxonomy


class Competency(Schema, ABC):
    """A competency that is required by the lecturer to be mastered by the student, enhanced with module-specific metadata."""
    id: int = Field(example=1)
    title: str = Field("", description="The title of the competency.", example="Competency 1")
    description: str = Field("", description="The description of the competency.", example="Competency 1 description")
    taxonomy: CompetencyTaxonomy = Field(None, description="The taxonomy of the competency.")

    meta: dict = Field(default_factory=dict, example={"internal_id": "5"})

    @validator('taxonomy', pre=True)
    def validate_taxonomy(cls, v):
        """Validate and convert taxonomy to the correct format."""
        if isinstance(v, str):
            return CompetencyTaxonomy.from_any_case(v)
        return v

    class Config:
        orm_mode = True