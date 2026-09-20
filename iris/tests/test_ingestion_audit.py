"""Tests for the read-back ingestion audit that certifies FINISHED runs."""

# pylint: disable=protected-access

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fitz
import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.ingestion_errors import (
    INGESTION_AUDIT_FAILED,
    IngestionStageError,
)
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.pipeline.ingestion_audit import (
    IngestionAudit,
    build_manifest,
    segments_are_complete,
)
from iris.pipeline.lecture_ingestion_update_pipeline import (
    LectureIngestionUpdatePipeline,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
)


def _pdf_base64(page_count: int) -> str:
    doc = fitz.open()
    for _ in range(page_count):
        doc.new_page()
    return base64.b64encode(doc.tobytes()).decode()


def _dto(
    pdf_base64: str = "",
    transcription: dict = None,
    attachment_version: int = 2,
    content_fingerprint: str = None,
) -> IngestionPipelineExecutionDto:
    lecture_unit = {
        "pdfFile": pdf_base64,
        "attachmentVersion": attachment_version,
        "contentFingerprint": content_fingerprint,
        "lectureUnitId": 3,
        "lectureId": 2,
        "courseId": 1,
        "lectureUnitName": "Unit",
        "lectureName": "Lecture",
        "courseName": "Course",
        "courseDescription": "",
        "lectureUnitLink": "",
        "videoLink": "",
    }
    if transcription is not None:
        lecture_unit["transcription"] = transcription
    return IngestionPipelineExecutionDto.model_validate(
        {
            "pyrisLectureUnit": lecture_unit,
            "lectureUnitId": 3,
            "settings": {
                "authenticationToken": "run-1",
                "artemisBaseUrl": "https://artemis.example",
            },
        }
    )


def _transcription(slide_numbers: list[int]) -> dict:
    return {
        "language": "en",
        "segments": [
            {
                "startTime": float(index),
                "endTime": float(index) + 1.0,
                "text": f"segment {index}",
                "slideNumber": slide_number,
            }
            for index, slide_number in enumerate(slide_numbers)
        ],
    }


def _collection(rows: list, *, ghost_uuids: frozenset = frozenset()) -> SimpleNamespace:
    """A collection mock whose fetch_object_by_id confirms every row except the
    given ghost uuids — the object-store confirmation every audit check now
    goes through. Defaulting to "everything confirmed" keeps every existing
    scenario testing the same thing it always did; only ghost-specific tests
    pass ghost_uuids.
    """
    by_uuid = {row.uuid: row for row in rows}

    def fetch_object_by_id(uid):
        return None if uid in ghost_uuids else by_uuid.get(uid)

    return SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows)),
            fetch_object_by_id=MagicMock(side_effect=fetch_object_by_id),
        )
    )


def _rows(
    schema_page_property: str,
    pages: list[int],
    version: int = None,
    run_id_property: str = None,
    run_id: str = "run-1",
) -> list:
    rows = []
    for index, page in enumerate(pages):
        properties = {schema_page_property: page}
        if version is not None:
            properties[LectureUnitPageChunkSchema.PAGE_VERSION.value] = version
        if run_id_property is not None:
            properties[run_id_property] = run_id
        rows.append(SimpleNamespace(properties=properties, uuid=f"uuid-{index}"))
    return rows


def _audit(
    chunk_pages=None,
    chunk_version=2,
    transcript_pages=None,
    segment_pages=None,
    unit_rows=1,
) -> IngestionAudit:
    return IngestionAudit(
        _collection(
            _rows(
                LectureUnitPageChunkSchema.PAGE_NUMBER.value,
                chunk_pages or [],
                version=chunk_version,
            )
        ),
        _collection(
            _rows(LectureTranscriptionSchema.PAGE_NUMBER.value, transcript_pages or [])
        ),
        _collection(
            _rows(LectureUnitSegmentSchema.PAGE_NUMBER.value, segment_pages or [])
        ),
        _collection(
            [
                SimpleNamespace(
                    properties={LectureUnitSchema.LECTURE_UNIT_ID.value: 3},
                    uuid=f"unit-row-{index}",
                )
                for index in range(unit_rows)
            ]
        ),
    )


def test_manifest_is_derived_from_the_request_inputs():
    dto = _dto(pdf_base64=_pdf_base64(3), transcription=_transcription([1, 1, 2]))

    manifest = build_manifest(dto)

    assert manifest.page_count == 3
    assert manifest.expected_pages == {1, 2, 3}
    assert manifest.transcript_slide_numbers == {1, 2}
    assert manifest.expected_segment_pages == {1, 2, 3}


def test_manifest_segment_range_follows_the_transcript_without_a_pdf():
    dto = _dto(transcription=_transcription([2, 4]))

    manifest = build_manifest(dto)

    assert manifest.page_count == 0
    assert manifest.expected_segment_pages == {2, 3, 4}


def test_audit_passes_for_a_complete_unit():
    dto = _dto(pdf_base64=_pdf_base64(3), transcription=_transcription([1, 2]))
    audit = _audit(
        chunk_pages=[1, 2, 3],
        transcript_pages=[1, 2],
        segment_pages=[1, 2, 3],
    )

    audit.verify(dto)


@pytest.mark.parametrize(
    ("audit_kwargs", "expected_problem"),
    [
        (
            {"chunk_pages": [1, 3], "segment_pages": [1, 2, 3]},
            "pages without chunks: [2]",
        ),
        (
            {"chunk_pages": [1, 2, 3], "chunk_version": 1, "segment_pages": [1, 2, 3]},
            "attachment version",
        ),
        (
            {"chunk_pages": [1, 2, 3, 4], "segment_pages": [1, 2, 3]},
            "chunks for nonexistent pages: [4]",
        ),
        (
            {"chunk_pages": [1, 2, 3], "segment_pages": [1, 3]},
            "slides without segment summaries: [2]",
        ),
        (
            {"chunk_pages": [1, 2, 3], "segment_pages": [1, 2, 3, 7]},
            "stale segment summaries: [7]",
        ),
        (
            {"chunk_pages": [1, 2, 3], "segment_pages": [1, 2, 3], "unit_rows": 2},
            "expected exactly one lecture unit row, found 2",
        ),
        (
            {
                "chunk_pages": [1, 2, 3],
                "segment_pages": [1, 2, 3],
                "transcript_pages": [5],
            },
            "transcription row(s) stored for a unit without a transcript",
        ),
    ],
)
def test_audit_fails_a_structurally_broken_unit(audit_kwargs, expected_problem):
    dto = _dto(pdf_base64=_pdf_base64(3))
    audit = _audit(**audit_kwargs)

    with pytest.raises(IngestionStageError) as exc_info:
        audit.verify(dto)

    assert exc_info.value.error_code == INGESTION_AUDIT_FAILED
    assert expected_problem in str(exc_info.value)


def test_audit_fails_when_the_stored_fingerprint_does_not_match():
    dto = _dto(pdf_base64=_pdf_base64(2), content_fingerprint="v1:expected")
    audit = _audit(chunk_pages=[1, 2], segment_pages=[1, 2])

    with pytest.raises(IngestionStageError) as exc_info:
        audit.verify(dto)

    assert "instead of 'v1:expected'" in str(exc_info.value)


def test_audit_fails_when_expected_transcript_rows_are_missing():
    dto = _dto(pdf_base64=_pdf_base64(2), transcription=_transcription([1, 2]))
    audit = _audit(chunk_pages=[1, 2], transcript_pages=[1], segment_pages=[1, 2])

    with pytest.raises(IngestionStageError) as exc_info:
        audit.verify(dto)

    assert "transcript slides without rows: [2]" in str(exc_info.value)


def test_run_ingestion_audits_before_the_terminal_callback():
    pipeline = object.__new__(LectureIngestionUpdatePipeline)
    pipeline.dto = _dto()
    pipeline.variant_id = "default"
    pipeline._is_local = False
    pipeline.cancel_event = None
    callback = MagicMock()
    order = []
    callback.finish.side_effect = lambda **_kwargs: order.append("finish")

    with (
        patch("iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"),
        patch("iris.pipeline.lecture_ingestion_update_pipeline.delete_many_with_retry"),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.LectureUnitPipeline"
        ) as unit_pipeline_cls,
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionAudit"
        ) as audit_cls,
    ):
        unit_pipeline_cls.return_value.return_value = []
        audit_cls.for_client.return_value.verify.side_effect = (
            lambda _dto: order.append("audit")
        )
        pipeline._run_ingestion(callback, {})

    assert order == ["audit", "finish"]


def test_run_fails_with_audit_code_when_the_audit_rejects_the_unit():
    pipeline = object.__new__(LectureIngestionUpdatePipeline)
    pipeline.dto = _dto()
    pipeline.variant_id = "default"
    pipeline._is_local = False
    pipeline.cancel_event = None
    callback = MagicMock()

    with (
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionStatusCallback",
            return_value=callback,
        ),
        patch("iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"),
        patch("iris.pipeline.lecture_ingestion_update_pipeline.delete_many_with_retry"),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.LectureUnitPipeline"
        ) as unit_pipeline_cls,
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionAudit"
        ) as audit_cls,
    ):
        unit_pipeline_cls.fetch_existing_properties.return_value = {}
        unit_pipeline_cls.return_value.return_value = []
        audit_cls.for_client.return_value.verify.side_effect = IngestionStageError(
            INGESTION_AUDIT_FAILED, "pages without chunks: [2]"
        )
        pipeline._run()

    callback.finish.assert_not_called()
    callback.fail.assert_called_once()
    assert callback.fail.call_args.kwargs["code"] == INGESTION_AUDIT_FAILED


def test_run_ingestion_purges_stale_content_when_pdf_and_transcript_are_absent():
    # A dispatch with neither a PDF nor a transcript means Artemis currently
    # associates neither with the unit (removed, or never present). Any rows
    # still stored from an earlier generation are stale and must be purged, or
    # the manifest-based audit (which expects zero content here) would fail
    # forever with nothing able to clean them up.
    pipeline = object.__new__(LectureIngestionUpdatePipeline)
    pipeline.dto = _dto()
    pipeline.variant_id = "default"
    pipeline._is_local = False
    pipeline.cancel_event = None
    callback = MagicMock()

    page_chunk_collection = MagicMock()
    page_chunk_collection.data.delete_many.return_value = SimpleNamespace(
        failed=0, matches=0, successful=0
    )
    transcription_collection = MagicMock()
    transcription_collection.data.delete_many.return_value = SimpleNamespace(
        failed=0, matches=0, successful=0
    )

    with (
        patch("iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.init_lecture_unit_page_chunk_schema",
            return_value=page_chunk_collection,
        ),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.init_lecture_transcription_schema",
            return_value=transcription_collection,
        ),
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.LectureUnitPipeline"
        ) as unit_pipeline_cls,
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionAudit"
        ) as audit_cls,
    ):
        unit_pipeline_cls.return_value.return_value = []
        audit_cls.for_client.return_value.verify.return_value = None
        pipeline._run_ingestion(callback, {})

    page_chunk_collection.data.delete_many.assert_called_once()
    transcription_collection.data.delete_many.assert_called_once()


def test_segments_are_complete_is_true_when_nothing_is_expected():
    dto = _dto()

    assert segments_are_complete(object(), dto) is True


@patch("iris.pipeline.ingestion_audit.IngestionAudit.for_client")
def test_segments_are_complete_true_when_stored_segments_cover_the_manifest(
    for_client,
):
    dto = _dto(pdf_base64=_pdf_base64(3))
    for_client.return_value = _audit(segment_pages=[1, 2, 3])

    assert segments_are_complete(object(), dto) is True


@patch("iris.pipeline.ingestion_audit.IngestionAudit.for_client")
def test_segments_are_complete_false_when_a_segment_is_missing(for_client):
    dto = _dto(pdf_base64=_pdf_base64(3))
    for_client.return_value = _audit(segment_pages=[1, 3])

    assert segments_are_complete(object(), dto) is False


def test_page_chunk_audit_ignores_a_ghost_generation():
    # A ghost generation (scan-visible, object-store-missing) coexisting with the
    # real one must not read as "multiple generations coexist" and fail an
    # otherwise fully-covered unit.
    dto = _dto(pdf_base64=_pdf_base64(2))
    real_rows = _rows(
        LectureUnitPageChunkSchema.PAGE_NUMBER.value,
        [1, 2],
        version=2,
        run_id_property=LectureUnitPageChunkSchema.INGESTION_RUN_ID.value,
        run_id="run-real",
    )
    ghost_rows = _rows(
        LectureUnitPageChunkSchema.PAGE_NUMBER.value,
        [1, 2],
        version=2,
        run_id_property=LectureUnitPageChunkSchema.INGESTION_RUN_ID.value,
        run_id="run-ghost",
    )
    for index, row in enumerate(ghost_rows):
        row.uuid = f"ghost-uuid-{index}"
    page_chunk_collection = _collection(
        real_rows + ghost_rows,
        ghost_uuids=frozenset(row.uuid for row in ghost_rows),
    )

    audit = IngestionAudit(
        page_chunk_collection,
        _collection([]),
        _collection(_rows(LectureUnitSegmentSchema.PAGE_NUMBER.value, [1, 2])),
        _collection(
            [
                SimpleNamespace(
                    properties={LectureUnitSchema.LECTURE_UNIT_ID.value: 3},
                    uuid="unit-row-0",
                )
            ]
        ),
    )

    audit.verify(dto)


def test_segment_audit_ignores_a_ghost_row_but_still_catches_a_real_gap():
    # The ghost row stands at the one genuinely missing page; excluding it must
    # not accidentally count it as coverage and hide the real gap.
    dto = _dto(pdf_base64=_pdf_base64(2))
    confirmed_row = _rows(LectureUnitSegmentSchema.PAGE_NUMBER.value, [1])[0]
    ghost_row = _rows(LectureUnitSegmentSchema.PAGE_NUMBER.value, [2])[0]
    ghost_row.uuid = "ghost-segment"
    segment_collection = _collection(
        [confirmed_row, ghost_row], ghost_uuids=frozenset({"ghost-segment"})
    )

    audit = IngestionAudit(
        _collection(
            _rows(LectureUnitPageChunkSchema.PAGE_NUMBER.value, [1, 2], version=2)
        ),
        _collection([]),
        segment_collection,
        _collection(
            [
                SimpleNamespace(
                    properties={LectureUnitSchema.LECTURE_UNIT_ID.value: 3},
                    uuid="unit-row-0",
                )
            ]
        ),
    )

    with pytest.raises(IngestionStageError) as exc_info:
        audit.verify(dto)

    assert "slides without segment summaries: [2]" in str(exc_info.value)


def test_unit_row_audit_ignores_a_ghost_duplicate():
    # A scan-visible, object-store-missing duplicate unit row must not read as
    # a genuine second row and fail an otherwise single-row unit.
    dto = _dto(pdf_base64=_pdf_base64(1))
    real_row = SimpleNamespace(
        properties={LectureUnitSchema.LECTURE_UNIT_ID.value: 3},
        uuid="unit-row-real",
    )
    ghost_row = SimpleNamespace(
        properties={LectureUnitSchema.LECTURE_UNIT_ID.value: 3},
        uuid="unit-row-ghost",
    )
    unit_collection = _collection(
        [real_row, ghost_row], ghost_uuids=frozenset({"unit-row-ghost"})
    )

    audit = IngestionAudit(
        _collection(
            _rows(LectureUnitPageChunkSchema.PAGE_NUMBER.value, [1], version=2)
        ),
        _collection([]),
        _collection(_rows(LectureUnitSegmentSchema.PAGE_NUMBER.value, [1])),
        unit_collection,
    )

    audit.verify(dto)
