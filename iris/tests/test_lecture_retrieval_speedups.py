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
        search_query="merge sort recurrence",
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
    )

    retrieval.lecture_transcription_pipeline.assert_not_called()
    retrieval.get_lecture_transcription_of_lecture_unit.assert_not_called()
    assert result.lecture_transcriptions == []

    segment_call = retrieval.lecture_unit_segment_pipeline.call_args
    assert segment_call.args[0] == "merge sort recurrence"

    retrieval(
        search_query="merge sort recurrence",
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
    )

    assert (
        retrieval.lecture_transcription_collection.query.fetch_objects.call_count == 1
    )


def test_the_agent_query_is_searched_in_every_domain_without_rewrites():
    retrieval = _make_retrieval(probe_objects=[SimpleNamespace(uuid=uuid4())])
    retrieval.lecture_unit_segment_pipeline.return_value = [_segment()]
    retrieval.lecture_transcription_pipeline.return_value = [_transcription()]
    retrieval.lecture_unit_page_chunk_pipeline.return_value = [_page_chunk()]

    result = retrieval(
        search_query="merge sort recurrence",
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
    )

    for pipeline in (
        retrieval.lecture_unit_segment_pipeline,
        retrieval.lecture_transcription_pipeline,
        retrieval.lecture_unit_page_chunk_pipeline,
    ):
        pipeline.assert_called_once()
        assert pipeline.call_args.args[0] == "merge sort recurrence"
        assert pipeline.call_args.kwargs["query_vector"] == [
            len("merge sort recurrence")
        ]
    # The query is embedded once and the vector is shared.
    retrieval.llm_embedding.embed.assert_called_once_with("merge sort recurrence")
    assert result.lecture_transcriptions
    rerank_queries = {
        call.args[0] for call in retrieval.cohere_client.rerank.call_args_list
    }
    assert rerank_queries == {"merge sort recurrence"}


def test_lecture_and_faq_retrieval_resolve_no_chat_model(monkeypatch):
    """The agent writes the search query, so retrieval needs no chat model; the
    reranker follows local mode."""
    from iris.retrieval import basic_retrieval, faq_retrieval
    from iris.retrieval.lecture import (
        lecture_page_chunk_retrieval,
        lecture_retrieval,
        lecture_transcription_retrieval,
        lecture_unit_segment_retrieval,
    )

    roles = []

    def resolve(pipeline_id, _variant, role, local):
        roles.append((pipeline_id, role, local))
        return "shared-model"

    for module in (
        basic_retrieval,
        lecture_retrieval,
        lecture_page_chunk_retrieval,
        lecture_transcription_retrieval,
        lecture_unit_segment_retrieval,
    ):
        monkeypatch.setattr(module, "resolve_model", resolve)
        monkeypatch.setattr(
            module,
            "LlmRequestHandler",
            lambda model_id: SimpleNamespace(model_id=model_id),
        )
        if hasattr(module, "RerankRequestHandler"):
            monkeypatch.setattr(module, "RerankRequestHandler", MagicMock())
        for name in dir(module):
            if name.startswith("init_") and name.endswith("_schema"):
                monkeypatch.setattr(module, name, MagicMock())
    monkeypatch.setattr(faq_retrieval, "init_faq_schema", MagicMock())

    lecture_retrieval.LectureRetrieval(MagicMock(), local=True)
    faq_retrieval.FaqRetrieval(MagicMock())

    assert roles
    assert all(role in {"embedding", "reranker"} for _pipeline, role, _local in roles)
    # Only the reranker follows the course's local mode; the query embedding has
    # to match the ingested vectors either way.
    assert {local for _pipeline, role, local in roles if role == "reranker"} == {True}
    assert {local for _pipeline, role, local in roles if role == "embedding"} == {False}
    assert len([1 for _pipeline, role, _local in roles if role == "reranker"]) == 4


def test_final_reranks_run_concurrently_and_preserve_results():
    retrieval = _make_retrieval(probe_objects=[SimpleNamespace(uuid=uuid4())])
    transcription = _transcription("Original transcript")
    page_chunk = _page_chunk("Original page")
    reranked_transcription = _transcription("Reranked transcript")
    reranked_page_chunk = _page_chunk("Reranked page")

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
        search_query="student query",
        course_id=1,
        lecture_id=2,
        lecture_unit_id=3,
    )

    assert result.lecture_transcriptions == [reranked_transcription]
    assert result.lecture_unit_page_chunks == [reranked_page_chunk]
    assert {
        call.kwargs["content_field_name"]
        for call in retrieval.cohere_client.rerank.call_args_list
    } == {"segment_text", "page_text_content"}


def test_subpipelines_embed_the_query_themselves_without_a_vector():
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
