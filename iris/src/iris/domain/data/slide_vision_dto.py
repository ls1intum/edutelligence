from pydantic.v1 import BaseModel, Field


class SlideVisionDTO(BaseModel):
    """Structured output from vision-based slide analysis."""

    display_page_number: int = Field(
        description=(
            "The page/slide number shown on the slide "
            "(typically bottom-right corner). "
            "Return -1 if no number is visible."
        )
    )

    academic_description: str = Field(
        description=(
            "Academic interpretation of the slide content. "
            "Describe the key concepts, diagrams, formulas, or text structure. "
            "Even for text-only slides, note how information is organized. "
            "Maximum 350 words."
        )
    )
