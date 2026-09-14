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
    # Defaulted, not required: a redacted message carries no content, and Artemis serializes the
    # payload with NON_EMPTY, which drops an empty string from the wire entirely.
    content: str = ""
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    is_iris_draft: bool = Field(default=False, alias="isIrisDraft")
    # The answer whose event triggered this ingestion (Trigger A: the just-verified
    # Iris draft; Trigger B: the just-marked answer). At most one per thread.
    is_verified_answer: bool = Field(default=False, alias="isVerifiedAnswer")
    # The durable ``resolvesPost`` flag. A thread may carry several, since Artemis
    # marks a post resolved if *any* of its answers resolves it.
    resolves_post: bool = Field(default=False, alias="resolvesPost")
    # The author opted out of having their content used by AI. ``content`` is empty and the
    # message is rendered as a placeholder: Iris may know a message sits at this point in the
    # thread, but never sees its text. Artemis clears the flags above on redacted messages, so a
    # placeholder can never be pulled into the extracted answer.
    redacted: bool = Field(default=False)
