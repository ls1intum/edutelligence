from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ThreadMessageDTO(BaseModel):
    """A single message in a communication-channel thread.

    Used as the raw input the course-memory Q/A extractor reads. ``author_role``
    distinguishes student / tutor / iris so the extractor can weight the messages.

    Which message holds the verified answer is stated explicitly by Artemis via
    ``is_verified_answer`` / ``resolves_post`` — never inferred from ``id``. Ids
    live in a single flat namespace here while Artemis draws them from two tables
    with independent sequences, so they are namespace-qualified (``post-7`` /
    ``answer-7``) and are for backlinking only.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    author_role: str = Field(alias="authorRole")
    content: str
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    is_iris_draft: bool = Field(default=False, alias="isIrisDraft")
    # The answer whose event triggered this ingestion (Trigger A: the just-verified
    # Iris draft; Trigger B: the just-marked answer). At most one per thread.
    is_verified_answer: bool = Field(default=False, alias="isVerifiedAnswer")
    # The durable ``resolvesPost`` flag. A thread may carry several, since Artemis
    # marks a post resolved if *any* of its answers resolves it.
    resolves_post: bool = Field(default=False, alias="resolvesPost")
