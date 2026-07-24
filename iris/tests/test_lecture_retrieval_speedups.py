"""Tests for lecture retrieval latency optimizations."""

# pylint: skip-file

from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (  # noqa: E402
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
    LectureUnitRetrievalDTO,
    LectureUnitSegmentRetrievalDTO,
)
from iris.llm.llm_configuration import LlmConfigurationError  # noqa: E402
from iris.retrieval.lecture.lecture_page_chunk_retrieval import (  # noqa: E402
    LecturePageChunkRetrieval,
)
from iris.retrieval.lecture.lecture_retrieval import (  # noqa: E402
    LectureRetrieval,
    QueryRewriteMode,
)
from iris.retrieval.lecture.lecture_unit_segment_retrieval import (  # noqa: E402
    LectureUnitSegmentRetrieval,
)


def _lecture_unit() -> LectureUnitRetrievalDTO:
    return LectureUnitRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Description",
        course_language="en",
        lecture_id=2,
        lecture_name="Lecture",
        lecture_unit_id=3,
        lecture_unit_name="Unit",
        lecture_unit_link="http://example.com/unit",
        video_link="http://example.com/video",
        base_url="http://example.com",
        lecture_unit_summary="Unit summary",
    )


def _segment() -> LectureUnitSegmentRetrievalDTO:
    return LectureUnitSegmentRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Description",
        lecture_id=2,
        lecture_name="Lecture",
        lecture_unit_id=3,
        lecture_unit_name="Unit",
        lecture_unit_link="http://example.com/unit",
        video_link="http://example.com/video",
        page_number=4,
        display_page_number=4,
        segment_summary="Segment summary",
        base_url="http://example.com",
    )


def _transcription(text: str = "Transcript") -> LectureTranscriptionRetrievalDTO:
    return LectureTranscriptionRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Description",
        lecture_id=2,
        lecture_name="Lecture",
        lecture_unit_id=3,
        lecture_unit_name="Unit",
        video_link="http://example.com/video",
        language="en",
        segment_start_time=0.0,
        segment_end_time=10.0,
        page_number=4,
        segment_summary="Summary",
        segment_text=text,
        base_url="http://example.com",
    )


def _page_chunk(text: str = "Slide") -> LectureUnitPageChunkRetrievalDTO:
    return LectureUnitPageChunkRetrievalDTO(
        uuid=str(uuid4()),
        course_id=1,
        course_name="Course",
        course_description="Description",
        lecture_id=2,
        lecture_name="Lecture",
        lecture_unit_id=3,
        lecture_unit_name="Unit",
        lecture_unit_link="http://example.com/unit",
        course_language="en",
        page_number=4,
        display_page_number=4,
        page_text_content=text,
        base_url="http://example.com",
    )


def _make_retrieval(probe_objects=None) -> LectureRetrieval:
    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval.get_lecture_unit = MagicMock(return_value=_lecture_unit())
    retrieval._transcription_presence_cache = {}

    retrieval.lecture_transcription_collection = MagicMock()
    retrieval.lecture_transcription_collection.query.fetch_objects.return_value = (
        SimpleNamespace(objects=probe_objects if probe_objects is not None else [])
    )

    retrieval.rewrite_student_query = MagicMock(
        side_effect=lambda _history, _query, _language, _course, mode: (
            f"rewrite-{mode.value}"
        )
    )
    retrieval.rewrite_elaborated_query = MagicMock(
        side_effect=lambda _history, _query, _language, _course, mode: (
            f"hyde-{mode.value}"
        )
    )

    retrieval.llm_embedding = MagicMock()
    retrieval.llm_embedding.embed.side_effect = lambda query: [len(query)]

    retrieval.lecture_unit_segment_pipeline = MagicMock(return_value=[])
    retrieval.lecture_transcription_pipeline = MagicMock(return_value=[])
    retrieval.lecture_unit_page_chunk_pipeline = MagicMock(return_value=[])
    retrieval.get_lecture_transcription_of_lecture_unit = MagicMock(return_value=[])
    retrieval.get_lecture_page_chunks_of_lecture_unit = MagicMock(return_value=[])

    retrieval.cohere_client = MagicMock()
    retrieval.cohere_client.rerank.side_effect = (
        lambda _query, documents, *_args, **_kwargs: documents
    )
    return retrieval


def test_no_transcriptions_skips_transcription_domain_and_caches_probe():
    retrieval = _make_retrieval(probe_objects=[])
    retrieval.lecture_unit_segment_pipeline.return_value = [_segment()]
    retrieval.get_lecture_transcription_of_lecture_unit.return_value = [
        _transcription("Should not be fetched")
    ]

    result = retrieval(
        "student query",
        course_id=1,
        chat_history=[],
        lecture_id=2,
        lecture_unit_id=3,
    )

    assert retrieval.rewrite_student_query.call_count == 1
    assert retrieval.rewrite_elaborated_query.call_count == 1
    assert retrieval.rewrite_student_query.call_args.args[-1] == (
        QueryRewriteMode.LECTURE_PAGES
    )
    assert retrieval.rewrite_elaborated_query.call_args.args[-1] == (
        QueryRewriteMode.LECTURE_PAGES
    )
    retrieval.lecture_transcription_pipeline.assert_not_called()
    retrieval.get_lecture_transcription_of_lecture_unit.assert_not_called()
    assert result.lecture_transcriptions == []

    segment_call = retrieval.lecture_unit_segment_pipeline.call_args
    assert segment_call.args[1] == "rewrite-lecture_pages"
    assert segment_call.args[2] == "hyde-lecture_pages"

    retrieval(
        "student query",
        course_id=1,
        chat_history=[],
        lecture_id=2,
        lecture_unit_id=3,
    )

    assert (
        retrieval.lecture_transcription_collection.query.fetch_objects.call_count == 1
    )


def test_existing_transcriptions_keep_all_rewrites_and_pipelines():
    retrieval = _make_retrieval(probe_objects=[SimpleNamespace(uuid=uuid4())])
    retrieval.lecture_unit_segment_pipeline.return_value = [_segment()]
    retrieval.lecture_transcription_pipeline.return_value = [_transcription()]
    retrieval.lecture_unit_page_chunk_pipeline.return_value = [_page_chunk()]

    result = retrieval(
        "student query",
        course_id=1,
        chat_history=[],
        lecture_id=2,
        lecture_unit_id=3,
    )

    assert retrieval.rewrite_student_query.call_count == 2
    assert retrieval.rewrite_elaborated_query.call_count == 2
    retrieval.lecture_unit_segment_pipeline.assert_called_once()
    retrieval.lecture_transcription_pipeline.assert_called_once()
    retrieval.lecture_unit_page_chunk_pipeline.assert_called_once()
    assert result.lecture_transcriptions
    assert (
        retrieval.lecture_transcription_collection.query.fetch_objects.call_count == 1
    )


def test_final_reranks_run_concurrently_and_preserve_results():
    retrieval = _make_retrieval(probe_objects=[SimpleNamespace(uuid=uuid4())])
    transcription = _transcription("Original transcript")
    page_chunk = _page_chunk("Original page")
    reranked_transcription = _transcription("Reranked transcript")
    reranked_page_chunk = _page_chunk("Reranked page")

    retrieval.run_parallel_rewrite_tasks = MagicMock(
        return_value=(
            "page rewrite",
            "transcription rewrite",
            "page hyde",
            "trans hyde",
        )
    )
    retrieval.lecture_unit_segment_pipeline.return_value = []
    retrieval.lecture_transcription_pipeline.return_value = [transcription]
    retrieval.lecture_unit_page_chunk_pipeline.return_value = [page_chunk]

    barrier = Barrier(2, timeout=1.0)

    def rerank(_query, documents, *_args, **kwargs):
        barrier.wait()
        if kwargs["content_field_name"] == "segment_text":
            assert documents == [transcription]
            return [reranked_transcription]
        assert kwargs["content_field_name"] == "page_text_content"
        assert documents == [page_chunk]
        return [reranked_page_chunk]

    retrieval.cohere_client.rerank.side_effect = rerank

    result = retrieval(
        "student query",
        course_id=1,
        chat_history=[],
        lecture_id=2,
        lecture_unit_id=3,
    )

    assert result.lecture_transcriptions == [reranked_transcription]
    assert result.lecture_unit_page_chunks == [reranked_page_chunk]
    assert {
        call.kwargs["content_field_name"]
        for call in retrieval.cohere_client.rerank.call_args_list
    } == {"segment_text", "page_text_content"}


def test_distinct_queries_embed_once_and_subpipeline_fallback_still_embeds():
    retrieval = _make_retrieval(probe_objects=[SimpleNamespace(uuid=uuid4())])
    retrieval.run_parallel_rewrite_tasks = MagicMock(
        return_value=("same query", "same query", "same query", "same query")
    )
    retrieval.lecture_unit_segment_pipeline.return_value = []
    retrieval.lecture_transcription_pipeline.return_value = []
    retrieval.lecture_unit_page_chunk_pipeline.return_value = []

    retrieval(
        "student query",
        course_id=1,
        chat_history=[],
        lecture_id=2,
        lecture_unit_id=3,
    )

    retrieval.llm_embedding.embed.assert_called_once_with("same query")

    segment_call = retrieval.lecture_unit_segment_pipeline.call_args
    transcription_call = retrieval.lecture_transcription_pipeline.call_args
    page_chunk_call = retrieval.lecture_unit_page_chunk_pipeline.call_args
    assert segment_call.kwargs["rewritten_query_vector"] == [len("same query")]
    assert transcription_call.kwargs["hypothetical_answer_vector"] == [
        len("same query")
    ]
    assert page_chunk_call.kwargs["rewritten_query_vector"] == [len("same query")]

    segment_retrieval = LectureUnitSegmentRetrieval.__new__(LectureUnitSegmentRetrieval)
    segment_retrieval.llm_embedding = MagicMock()
    segment_retrieval.llm_embedding.embed.return_value = [1, 2, 3]
    segment_retrieval.collection = MagicMock()
    segment_retrieval.collection.query.hybrid.return_value = SimpleNamespace(objects=[])

    segment_retrieval.search_in_db(_lecture_unit(), "standalone", 0.9, 10)

    segment_retrieval.llm_embedding.embed.assert_called_once_with("standalone")

    page_retrieval = LecturePageChunkRetrieval.__new__(LecturePageChunkRetrieval)
    page_retrieval.llm_embedding = MagicMock()
    page_retrieval.llm_embedding.embed.return_value = [4, 5, 6]
    page_retrieval.lecture_unit_page_chunk_collection = MagicMock()
    page_retrieval.lecture_unit_page_chunk_collection.query.hybrid.return_value = (
        SimpleNamespace(objects=[])
    )

    page_retrieval.search_in_db("standalone", 0.9, 10, _lecture_unit())

    page_retrieval.llm_embedding.embed.assert_called_once_with("standalone")


def _embedding_guard_retrieval(
    parent_model, segment_model, transcription_model, page_model
) -> LectureRetrieval:
    """Build a bare LectureRetrieval wired only with the attributes the shared
    embedding-model guard inspects."""
    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval.llm_embedding = SimpleNamespace(model_id=parent_model)
    retrieval.lecture_unit_segment_pipeline = SimpleNamespace(
        llm_embedding=SimpleNamespace(model_id=segment_model)
    )
    retrieval.lecture_transcription_pipeline = SimpleNamespace(
        llm_embedding=SimpleNamespace(model_id=transcription_model)
    )
    retrieval.lecture_unit_page_chunk_pipeline = SimpleNamespace(
        llm_embedding=SimpleNamespace(model_id=page_model)
    )
    return retrieval


def test_shared_embedding_guard_passes_when_all_models_match():
    retrieval = _embedding_guard_retrieval(
        "oai-embedding-small",
        "oai-embedding-small",
        "oai-embedding-small",
        "oai-embedding-small",
    )
    # Should not raise: reusing the shared query vectors is safe here.
    retrieval._assert_shared_embedding_model()


def test_shared_embedding_guard_raises_when_segment_model_differs():
    retrieval = _embedding_guard_retrieval(
        "oai-embedding-small",
        "oai-embedding-large",
        "oai-embedding-small",
        "oai-embedding-small",
    )
    with pytest.raises(LlmConfigurationError) as exc_info:
        retrieval._assert_shared_embedding_model()

    message = str(exc_info.value)
    assert "lecture_unit_segment_retrieval_pipeline" in message
    assert "oai-embedding-large" in message
    assert "oai-embedding-small" in message


def test_shared_embedding_guard_raises_when_transcription_model_differs():
    retrieval = _embedding_guard_retrieval(
        "oai-embedding-small",
        "oai-embedding-small",
        "voyage-3",
        "oai-embedding-small",
    )
    with pytest.raises(LlmConfigurationError) as exc_info:
        retrieval._assert_shared_embedding_model()

    assert "lecture_transcriptions_retrieval_pipeline" in str(exc_info.value)


def test_page_chunk_lookup_skips_none_filter_values():
    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval.lecture_unit_page_chunk_collection = MagicMock()
    segment = _segment()
    segment.base_url = None

    assert retrieval.get_lecture_page_chunks_of_lecture_unit(segment) == []
    retrieval.lecture_unit_page_chunk_collection.query.fetch_objects.assert_not_called()
