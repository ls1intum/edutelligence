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
