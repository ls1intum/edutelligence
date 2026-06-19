from types import SimpleNamespace
from unittest.mock import MagicMock

from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)


def test_skip_path_restores_display_page_numbers_from_existing_chunks(monkeypatch):
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)

    lecture_unit = SimpleNamespace(
        pdf_file_base64="",
        attachment_version=7,
        course_id=11,
        lecture_id=12,
        lecture_unit_id=13,
        display_page_numbers=None,
    )
    pipeline.dto = SimpleNamespace(
        lecture_unit=lecture_unit,
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
    )
    pipeline.callback = SimpleNamespace(
        skip=MagicMock(),
        error=MagicMock(),
    )
    pipeline.tokens = []
    pipeline.course_language = None
    pipeline.get_course_language = MagicMock(return_value="en")

    version_chunk = SimpleNamespace(
        properties={LectureUnitPageChunkSchema.PAGE_VERSION.value: 7}
    )
    existing_chunks = [
        SimpleNamespace(
            properties={
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 2,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 20,
            }
        ),
        SimpleNamespace(
            properties={
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 1,
            }
        ),
        SimpleNamespace(
            properties={
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 2,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 99,
            }
        ),
        SimpleNamespace(
            properties={
                LectureUnitPageChunkSchema.PAGE_NUMBER.value: 3,
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: -1,
            }
        ),
    ]
    pipeline.collection = SimpleNamespace(
        query=SimpleNamespace(
            fetch_objects=MagicMock(
                side_effect=[
                    SimpleNamespace(objects=[version_chunk]),
                    SimpleNamespace(objects=existing_chunks),
                ]
            )
        )
    )

    fake_doc = SimpleNamespace(
        page_count=1,
        load_page=MagicMock(
            return_value=SimpleNamespace(get_text=MagicMock(return_value="page text"))
        ),
    )
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.save_pdf",
        MagicMock(return_value="/tmp/test.pdf"),
    )
    cleanup_mock = MagicMock()
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.cleanup_temporary_file",
        cleanup_mock,
    )
    monkeypatch.setattr(
        "iris.pipeline.lecture_ingestion_pipeline.fitz.open",
        MagicMock(return_value=fake_doc),
    )

    course_language, tokens = pipeline()

    assert course_language == "en"
    assert not tokens
    assert pipeline.dto.lecture_unit.display_page_numbers == [1, 20, -1]
    assert pipeline.collection.query.fetch_objects.call_count == 2
    assert (
        pipeline.collection.query.fetch_objects.call_args_list[1].kwargs["limit"]
        == 10000
    )
    cleanup_mock.assert_called_once_with("/tmp/test.pdf")
    assert pipeline.callback.skip.call_count == 3
    pipeline.callback.error.assert_not_called()
