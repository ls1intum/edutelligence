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
from iris.pipeline.ingestion_audit import IngestionAudit, build_manifest
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
    pdf_base64: str = "", transcription: dict = None, attachment_version: int = 2
) -> IngestionPipelineExecutionDto:
    lecture_unit = {
        "pdfFile": pdf_base64,
        "attachmentVersion": attachment_version,
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


def _collection(rows: list) -> SimpleNamespace:
    return SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(return_value=SimpleNamespace(objects=rows))
        )
    )


def _rows(schema_page_property: str, pages: list[int], version: int = None) -> list:
    rows = []
    for page in pages:
        properties = {schema_page_property: page}
        if version is not None:
            properties[LectureUnitPageChunkSchema.PAGE_VERSION.value] = version
        rows.append(SimpleNamespace(properties=properties))
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
                SimpleNamespace(properties={LectureUnitSchema.LECTURE_UNIT_ID.value: 3})
                for _ in range(unit_rows)
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
    callback = MagicMock()
    order = []
    callback.finish.side_effect = lambda **_kwargs: order.append("finish")

    with (
        patch("iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"),
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
    callback = MagicMock()

    with (
        patch(
            "iris.pipeline.lecture_ingestion_update_pipeline.IngestionStatusCallback",
            return_value=callback,
        ),
        patch("iris.pipeline.lecture_ingestion_update_pipeline.VectorDatabase"),
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
