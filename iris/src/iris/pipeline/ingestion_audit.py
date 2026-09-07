"""Read-back audit that makes FINISHED a verified claim.

Before the terminal callback, the ingestion run re-reads what Weaviate
actually holds for the lecture unit and compares it against a manifest
derived purely from the request inputs: the PDF's page count, the
transcript's slide numbers, and the attachment version. Any deviation, such
as a missing page, a chunk from an older attachment version, a transcript
that should or should not exist, a segment gap, or a duplicated unit row,
fails the run instead of certifying a partial unit. The audit reads only
identity properties, never content, so it costs a handful of queries and no
LLM calls.
"""

import base64
from dataclasses import dataclass
from typing import Optional

import fitz
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.ingestion_errors import (
    INGESTION_AUDIT_FAILED,
    IngestionStageError,
)
from iris.common.logging_config import get_logger
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)

logger = get_logger(__name__)

_FETCH_LIMIT = 10_000


@dataclass(frozen=True)
class IngestionManifest:
    """What the index must hold for a unit, derived from the request inputs."""

    page_count: int
    attachment_version: Optional[int]
    transcript_slide_numbers: frozenset[int]

    @property
    def expects_pdf_content(self) -> bool:
        return self.page_count > 0

    @property
    def expects_transcript(self) -> bool:
        return bool(self.transcript_slide_numbers)

    @property
    def expected_pages(self) -> set[int]:
        return set(range(1, self.page_count + 1))

    @property
    def expected_segment_pages(self) -> set[int]:
        """Mirror the segment pipeline: a continuous range over the content."""
        if self.expects_pdf_content:
            return self.expected_pages
        if self.expects_transcript:
            return set(
                range(
                    min(self.transcript_slide_numbers),
                    max(self.transcript_slide_numbers) + 1,
                )
            )
        return set()


def build_manifest(dto: IngestionPipelineExecutionDto) -> IngestionManifest:
    """Derive the manifest from the request inputs alone."""
    page_count = 0
    pdf_base64 = dto.lecture_unit.pdf_file_base64
    if pdf_base64:
        with fitz.open(stream=base64.b64decode(pdf_base64), filetype="pdf") as doc:
            page_count = doc.page_count

    transcription = dto.lecture_unit.transcription
    slide_numbers: frozenset[int] = frozenset()
    if transcription is not None and transcription.segments:
        slide_numbers = frozenset(
            segment.slide_number for segment in transcription.segments
        )

    return IngestionManifest(
        page_count=page_count,
        attachment_version=dto.lecture_unit.attachment_version,
        transcript_slide_numbers=slide_numbers,
    )


class IngestionAudit:
    """Compare a unit's stored state against its manifest and fail on any gap."""

    def __init__(
        self,
        page_chunk_collection,
        transcription_collection,
        segment_collection,
        unit_collection,
    ):
        self.page_chunk_collection = page_chunk_collection
        self.transcription_collection = transcription_collection
        self.segment_collection = segment_collection
        self.unit_collection = unit_collection

    @classmethod
    def for_client(cls, client: WeaviateClient) -> "IngestionAudit":
        return cls(
            init_lecture_unit_page_chunk_schema(client),
            init_lecture_transcription_schema(client),
            init_lecture_unit_segment_schema(client),
            init_lecture_unit_schema(client),
        )

    def verify(self, dto: IngestionPipelineExecutionDto) -> None:
        """Raise ``IngestionStageError`` when the index deviates from the manifest."""
        manifest = build_manifest(dto)
        problems: list[str] = []
        problems.extend(self._verify_page_chunks(dto, manifest))
        problems.extend(self._verify_transcriptions(dto, manifest))
        problems.extend(self._verify_segments(dto, manifest))
        problems.extend(self._verify_unit_row(dto))

        if problems:
            summary = "; ".join(problems)
            raise IngestionStageError(
                INGESTION_AUDIT_FAILED,
                f"Ingestion audit failed for lecture unit "
                f"{dto.lecture_unit.lecture_unit_id}: {summary}",
            )
        logger.info(
            "[Lecture %d] Ingestion audit passed: %d pages, transcript=%s",
            dto.lecture_unit.lecture_unit_id,
            manifest.page_count,
            manifest.expects_transcript,
        )

    def _verify_page_chunks(
        self, dto: IngestionPipelineExecutionDto, manifest: IngestionManifest
    ) -> list[str]:
        chunks = self.page_chunk_collection.query.fetch_objects(
            filters=self._identity_filter(dto, LectureUnitPageChunkSchema),
            limit=_FETCH_LIMIT,
            return_properties=[
                LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                LectureUnitPageChunkSchema.PAGE_VERSION.value,
            ],
        ).objects

        if not manifest.expects_pdf_content:
            if chunks:
                return [f"{len(chunks)} page chunk(s) stored for a unit without a PDF"]
            return []

        problems = []
        pages: set[int] = set()
        stale_versions = 0
        for chunk in chunks:
            version = chunk.properties.get(
                LectureUnitPageChunkSchema.PAGE_VERSION.value
            )
            if version != manifest.attachment_version:
                stale_versions += 1
            page_number = chunk.properties.get(
                LectureUnitPageChunkSchema.PAGE_NUMBER.value
            )
            if page_number is not None:
                pages.add(int(page_number))

        if stale_versions:
            problems.append(
                f"{stale_versions} chunk(s) carry an attachment version other "
                f"than {manifest.attachment_version}"
            )
        missing_pages = manifest.expected_pages - pages
        if missing_pages:
            problems.append(f"pages without chunks: {sorted(missing_pages)}")
        unexpected_pages = pages - manifest.expected_pages
        if unexpected_pages:
            problems.append(f"chunks for nonexistent pages: {sorted(unexpected_pages)}")
        return problems

    def _verify_transcriptions(
        self, dto: IngestionPipelineExecutionDto, manifest: IngestionManifest
    ) -> list[str]:
        rows = self.transcription_collection.query.fetch_objects(
            filters=self._identity_filter(dto, LectureTranscriptionSchema),
            limit=_FETCH_LIMIT,
            return_properties=[LectureTranscriptionSchema.PAGE_NUMBER.value],
        ).objects

        if not manifest.expects_transcript:
            if rows:
                return [
                    f"{len(rows)} transcription row(s) stored for a unit "
                    f"without a transcript"
                ]
            return []

        stored_pages = {
            int(row.properties[LectureTranscriptionSchema.PAGE_NUMBER.value])
            for row in rows
            if row.properties.get(LectureTranscriptionSchema.PAGE_NUMBER.value)
            is not None
        }
        expected_pages = set(manifest.transcript_slide_numbers)
        problems = []
        missing = expected_pages - stored_pages
        if missing:
            problems.append(f"transcript slides without rows: {sorted(missing)}")
        unexpected = stored_pages - expected_pages
        if unexpected:
            problems.append(
                f"transcription rows for unknown slides: {sorted(unexpected)}"
            )
        return problems

    def _verify_segments(
        self, dto: IngestionPipelineExecutionDto, manifest: IngestionManifest
    ) -> list[str]:
        expected_pages = manifest.expected_segment_pages
        rows = self.segment_collection.query.fetch_objects(
            filters=self._identity_filter(dto, LectureUnitSegmentSchema),
            limit=_FETCH_LIMIT,
            return_properties=[LectureUnitSegmentSchema.PAGE_NUMBER.value],
        ).objects
        stored_pages = {
            int(row.properties[LectureUnitSegmentSchema.PAGE_NUMBER.value])
            for row in rows
            if row.properties.get(LectureUnitSegmentSchema.PAGE_NUMBER.value)
            is not None
        }

        problems = []
        missing = expected_pages - stored_pages
        if missing:
            problems.append(f"slides without segment summaries: {sorted(missing)}")
        unexpected = stored_pages - expected_pages
        if unexpected:
            problems.append(f"stale segment summaries: {sorted(unexpected)}")
        return problems

    def _verify_unit_row(self, dto: IngestionPipelineExecutionDto) -> list[str]:
        rows = self.unit_collection.query.fetch_objects(
            filters=self._identity_filter(dto, LectureUnitSchema),
            limit=10,
            return_properties=[LectureUnitSchema.LECTURE_UNIT_ID.value],
        ).objects
        if len(rows) != 1:
            return [f"expected exactly one lecture unit row, found {len(rows)}"]
        return []

    @staticmethod
    def _identity_filter(dto: IngestionPipelineExecutionDto, schema):
        return (
            Filter.by_property(schema.BASE_URL.value).equal(
                dto.settings.artemis_base_url
            )
            & Filter.by_property(schema.COURSE_ID.value).equal(
                dto.lecture_unit.course_id
            )
            & Filter.by_property(schema.LECTURE_ID.value).equal(
                dto.lecture_unit.lecture_id
            )
            & Filter.by_property(schema.LECTURE_UNIT_ID.value).equal(
                dto.lecture_unit.lecture_unit_id
            )
        )
