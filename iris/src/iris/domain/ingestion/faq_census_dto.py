"""DTOs for the FAQ census of one Artemis instance."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FaqCensusEntryDTO(BaseModel):
    """What the index holds for one FAQ.

    Owned rows carry the asking instance's base URL. Legacy rows were written before FAQ rows
    carried a base URL, so their owner is unknown:
    Artemis replaces them when it pushes the FAQ, but never deletes them as orphans.
    """

    model_config = ConfigDict(populate_by_name=True)

    course_id: int = Field(alias="courseId")
    faq_id: int = Field(alias="faqId")
    owned_row_count: int = Field(default=0, alias="ownedRowCount")
    legacy_row_count: int = Field(default=0, alias="legacyRowCount")
    owned_fingerprint: Optional[str] = Field(default=None, alias="ownedFingerprint")


class FaqCensusDTO(BaseModel):
    """Every FAQ row of one Artemis instance, plus legacy rows without a base URL."""

    model_config = ConfigDict(populate_by_name=True)

    faqs: list[FaqCensusEntryDTO] = Field(default_factory=list)
