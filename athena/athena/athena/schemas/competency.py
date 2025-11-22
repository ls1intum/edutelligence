from abc import ABC

from pydantic import field_validator, ConfigDict, Field

from .schema import Schema
from .competency_taxonomy import CompetencyTaxonomy


class Competency(Schema, ABC):
    """A competency that is required by the lecturer to be mastered by the student, enhanced with module-specific metadata."""
    id: int = Field(examples=[1])
    title: str = Field("", description="The title of the competency.", examples=["Competency 1"])
    description: str = Field("", description="The description of the competency.", examples=["Competency 1 description"])
    taxonomy: CompetencyTaxonomy = Field(None, description="The taxonomy of the competency.")

    meta: dict = Field(default_factory=dict, examples=[{"internal_id": "5"}])

    @field_validator('taxonomy', mode="before")
    @classmethod
    def validate_taxonomy(cls, v):
        """Validate and convert taxonomy to the correct format."""
        if isinstance(v, str):
            return CompetencyTaxonomy.from_any_case(v)
        return v
    model_config = ConfigDict(from_attributes=True)