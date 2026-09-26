"""Typed ingestion failures that carry a wire error code to Artemis.

An ingestion stage that cannot complete raises ``IngestionStageError`` instead
of degrading the stored content. The orchestrating pipeline sends exactly one
terminal FAILED callback with the carried ``error_code``, so Artemis can
classify the failure and schedule a retry instead of recording a partial unit
as successfully ingested.
"""

from typing import Optional

from iris.common.token_usage_dto import TokenUsageDTO


class IngestionStageError(Exception):
    """A lecture ingestion stage failed in a way that must fail the whole run."""

    def __init__(
        self,
        error_code: str,
        message: str,
        tokens: Optional[list[TokenUsageDTO]] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.tokens = tokens if tokens is not None else []


SLIDE_VISION_FAILED = "SLIDE_VISION_FAILED"
VECTOR_STORE_WRITE_FAILED = "VECTOR_STORE_WRITE_FAILED"
STALE_CONTENT_DELETE_FAILED = "STALE_CONTENT_DELETE_FAILED"
PAGE_INGESTION_FAILED = "PAGE_INGESTION_FAILED"
TRANSCRIPT_INGESTION_FAILED = "TRANSCRIPT_INGESTION_FAILED"
INGESTION_AUDIT_FAILED = "INGESTION_AUDIT_FAILED"
# Neither a PDF page nor a transcript row exists for the unit: a corrupt or
# genuinely empty attachment reached ingestion (Artemis only checks the file
# extension, not that the file has readable pages), and there is nothing to
# summarize or index. Raised early and explicitly instead of silently writing
# a placeholder segment that the audit would later reject with no indication
# of the real cause.
NO_INGESTIBLE_CONTENT = "NO_INGESTIBLE_CONTENT"
# A page-number span was derived from a fetch that hit its row cap. The cap counts rows,
# not pages, so the true minimum or maximum could sit in the untruncated remainder;
# trusting the capped subset would write and prune the wrong segment span and fail the
# manifest-based audit on every retry, since nothing about a wrong-but-plausible range
# self-heals. Raised instead of silently proceeding, mirroring
# check_if_attachment_needs_update's "never trust a possibly partial sample" rule for the
# same fetch bound.
PAGE_RANGE_FETCH_CAPPED = "PAGE_RANGE_FETCH_CAPPED"
