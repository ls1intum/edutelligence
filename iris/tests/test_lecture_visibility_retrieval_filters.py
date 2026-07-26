"""Regression tests for lecture visibility enforcement."""

# pylint: disable=protected-access

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from iris.pipeline.chat.mcq_chat_mixin import retrieve_lecture_content_for_mcq
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.retrieval.lecture.lecture_page_chunk_retrieval import (
    LecturePageChunkRetrieval,
)
from iris.retrieval.lecture.lecture_visibility import (
    is_segment_visible,
    is_slide_visible,
    is_unit_released,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.lecture_unit_segment_schema import LectureUnitSegmentSchema

NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)


def test_slide_with_future_hidden_until_is_not_visible():
    assert not is_slide_visible(
        {"hidden_until": datetime(2026, 7, 3, tzinfo=timezone.utc)}, now=NOW
    )


def test_slide_with_past_hidden_until_is_visible():
    assert is_slide_visible(
        {"hidden_until": datetime(2026, 7, 1, tzinfo=timezone.utc)}, now=NOW
    )


def test_slide_without_hidden_until_is_visible():
    assert is_slide_visible({}, now=NOW)


def test_visibility_helpers_accept_weaviate_rfc3339_strings():
    assert not is_segment_visible({"hidden_until": "2026-07-03T00:00:00Z"}, now=NOW)
    assert is_unit_released({"release_date": "2026-07-01T00:00:00Z"}, now=NOW)


def test_unreleased_unit_is_filtered():
    assert not is_unit_released(
        {"release_date": datetime(2026, 7, 3, tzinfo=timezone.utc)}, now=NOW
    )


def test_unit_without_release_date_is_released_for_backward_compatibility():
    assert is_unit_released({}, now=NOW)


def test_invalid_stored_visibility_value_fails_closed():
    assert not is_slide_visible({"hidden_until": "not-a-date"}, now=NOW)


def lecture_unit(release_date=None):
    return {
        LectureUnitSchema.BASE_URL.value: "https://artemis.example",
        LectureUnitSchema.LECTURE_UNIT_ID.value: 10,
        LectureUnitSchema.COURSE_NAME.value: "Course",
        LectureUnitSchema.LECTURE_NAME.value: "Lecture",
        LectureUnitSchema.LECTURE_UNIT_NAME.value: "Unit",
        LectureUnitSchema.RELEASE_DATE.value: release_date,
    }


def test_global_search_filters_hidden_slide_aggregate():
    props = {
        LectureUnitSegmentSchema.SEGMENT_SUMMARY.value: "Hidden summary",
        LectureUnitSegmentSchema.LECTURE_UNIT_ID.value: 10,
        LectureUnitSegmentSchema.BASE_URL.value: "https://artemis.example",
        LectureUnitSegmentSchema.COURSE_ID.value: 30,
        LectureUnitSegmentSchema.LECTURE_ID.value: 20,
        LectureUnitSegmentSchema.PAGE_NUMBER.value: 1,
        LectureUnitSegmentSchema.HIDDEN_UNTIL.value: datetime(
            2099, 1, 1, tzinfo=timezone.utc
        ),
    }

    assert (
        LectureGlobalSearchRetrieval._segment_to_dto(
            props,
            {("https://artemis.example", 10): lecture_unit()},
            {},
        )
        is None
    )


def test_global_search_filters_unreleased_transcription_but_not_released_one():
    props = {
        LectureTranscriptionSchema.SEGMENT_TEXT.value: "Transcript",
        LectureTranscriptionSchema.LECTURE_UNIT_ID.value: 10,
        LectureTranscriptionSchema.BASE_URL.value: "https://artemis.example",
        LectureTranscriptionSchema.COURSE_ID.value: 30,
        LectureTranscriptionSchema.LECTURE_ID.value: 20,
        LectureTranscriptionSchema.SEGMENT_START_TIME.value: 12.0,
    }
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)

    assert (
        LectureGlobalSearchRetrieval._transcription_to_dto(
            props,
            {("https://artemis.example", 10): lecture_unit(future)},
        )
        is None
    )
    assert (
        LectureGlobalSearchRetrieval._transcription_to_dto(
            props,
            {("https://artemis.example", 10): lecture_unit()},
        )
        is not None
    )


def test_mcq_content_excludes_hidden_slides_and_unreleased_units():
    db = SimpleNamespace(lectures=Mock(), lecture_units=Mock())
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.lectures.query.fetch_objects.return_value.objects = [
        SimpleNamespace(
            properties={
                "lecture_unit_id": 10,
                "lecture_id": 20,
                "page_number": 1,
                "page_text_content": "Hidden slide",
                "hidden_until": future,
                "base_url": "https://artemis.example",
            }
        ),
        SimpleNamespace(
            properties={
                "lecture_unit_id": 11,
                "lecture_id": 20,
                "page_number": 1,
                "page_text_content": "Unreleased slide",
                "hidden_until": None,
                "base_url": "https://artemis.example",
            }
        ),
        SimpleNamespace(
            properties={
                "lecture_unit_id": 12,
                "lecture_id": 20,
                "page_number": 1,
                "page_text_content": "Visible slide",
                "hidden_until": None,
                "base_url": "https://artemis.example",
            }
        ),
        SimpleNamespace(
            properties={
                "lecture_unit_id": 11,
                "lecture_id": 20,
                "page_number": 1,
                "page_text_content": "Foreign colliding slide",
                "hidden_until": None,
                "base_url": "https://other-artemis.example",
            }
        ),
    ]
    db.lecture_units.query.fetch_objects.return_value.objects = [
        SimpleNamespace(
            properties={
                "lecture_unit_id": 10,
                "lecture_name": "Lecture",
                "lecture_unit_name": "Hidden unit",
                "release_date": None,
                "base_url": "https://artemis.example",
            }
        ),
        SimpleNamespace(
            properties={
                "lecture_unit_id": 11,
                "lecture_name": "Lecture",
                "lecture_unit_name": "Future unit",
                "release_date": future,
                "base_url": "https://artemis.example",
            }
        ),
        SimpleNamespace(
            properties={
                "lecture_unit_id": 12,
                "lecture_name": "Lecture",
                "lecture_unit_name": "Visible unit",
                "release_date": None,
                "base_url": "https://artemis.example",
            }
        ),
        SimpleNamespace(
            properties={
                "lecture_unit_id": 11,
                "lecture_name": "Foreign lecture",
                "lecture_unit_name": "Foreign colliding unit",
                "release_date": None,
                "base_url": "https://other-artemis.example",
            }
        ),
    ]

    content, units = retrieve_lecture_content_for_mcq(
        db,
        course_id=30,
        base_url="https://artemis.example",
        allow_lecture_tool=True,
    )

    assert isinstance(content, str)
    content_text = content or ""
    assert "Visible slide" in content_text
    assert "Hidden slide" not in content_text
    assert "Unreleased slide" not in content_text
    assert "Foreign colliding slide" not in content_text
    assert [unit["lecture_unit_id"] for unit in units] == [12]
    assert db.lectures.query.fetch_objects.call_args.kwargs["limit"] == 10_000
    assert db.lecture_units.query.fetch_objects.call_args.kwargs["limit"] == 10_000


def test_page_search_fetches_next_window_after_hidden_candidates():
    retrieval = LecturePageChunkRetrieval.__new__(LecturePageChunkRetrieval)
    retrieval.llm_embedding = Mock()
    retrieval.llm_embedding.embed.return_value = [0.1]
    retrieval.lecture_unit_page_chunk_collection = Mock()
    hidden = SimpleNamespace(uuid="hidden", properties={"visible": False})
    visible = SimpleNamespace(uuid="visible", properties={"visible": True})
    retrieval.lecture_unit_page_chunk_collection.query.hybrid.side_effect = [
        SimpleNamespace(objects=[hidden]),
        SimpleNamespace(objects=[visible]),
    ]
    retrieval.generate_retrieval_dtos = Mock(
        side_effect=lambda properties, _uuid: (
            SimpleNamespace() if properties["visible"] else None
        )
    )

    result = retrieval.search_in_db(
        query="query",
        hybrid_factor=0.9,
        result_limit=1,
        lecture_unit_dto=SimpleNamespace(
            course_id=None, lecture_id=None, base_url=None
        ),
    )

    assert result == [visible]
    offsets = [
        call.kwargs["offset"]
        for call in retrieval.lecture_unit_page_chunk_collection.query.hybrid.call_args_list
    ]
    assert offsets == [0, 1]


def test_global_search_expands_candidates_until_visible_result_is_found():
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    hidden = SimpleNamespace()
    visible = SimpleNamespace()
    retrieval._search_segments = Mock(side_effect=[[hidden], [hidden, visible]])
    retrieval._search_video_transcriptions = Mock(side_effect=[[], []])
    visible_dto = SimpleNamespace()
    retrieval._map_search_objects = Mock(side_effect=[[], [], [(1.0, visible_dto)], []])

    result = retrieval._run_hybrid_search(
        query="query", vector=[0.1], alpha=0.5, limit=1
    )

    assert result == [visible_dto]
    candidate_limits = [
        call.args[3] for call in retrieval._search_segments.call_args_list
    ]
    assert candidate_limits == [1, 2]


def test_global_search_expands_each_saturated_source_before_merging_scores():
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    segment_hit = SimpleNamespace()
    hidden_transcription = SimpleNamespace()
    visible_transcription = SimpleNamespace()
    retrieval._search_segments = Mock(side_effect=[[segment_hit], [segment_hit]])
    retrieval._search_video_transcriptions = Mock(
        side_effect=[
            [hidden_transcription],
            [hidden_transcription, visible_transcription],
        ]
    )
    low_score_segment = SimpleNamespace()
    high_score_transcription = SimpleNamespace()
    retrieval._map_search_objects = Mock(
        side_effect=[
            [(0.2, low_score_segment)],
            [],
            [(0.2, low_score_segment)],
            [(0.9, high_score_transcription)],
        ]
    )

    result = retrieval._run_hybrid_search(
        query="query", vector=[0.1], alpha=0.5, limit=1
    )

    assert result == [high_score_transcription]
    transcription_candidate_limits = [
        call.args[3] for call in retrieval._search_video_transcriptions.call_args_list
    ]
    assert transcription_candidate_limits == [1, 2]
