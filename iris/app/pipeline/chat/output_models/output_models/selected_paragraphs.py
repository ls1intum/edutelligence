from typing import List

from pydantic import Field, BaseModel


class SelectedParagraphs(BaseModel):
    selected_paragraphs: List[int] = Field(
        default=[],
        description="List of paragraphs sorted from most relevant to least relevant to the student question, "
                    "each with a relevance score.",
    )
