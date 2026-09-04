"""Regression tests for lecture visibility enforcement."""

# pylint: disable=protected-access

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from iris.pipeline.chat import mcq_chat_mixin
from iris.pipeline.chat.mcq_chat_mixin import retrieve_lecture_content_for_mcq
from iris.retrieval.lecture.lecture_global_search_retrieval import (
    LectureGlobalSearchRetrieval,
)
from iris.retrieval.lecture.lecture_page_chunk_retrieval import (
    LecturePageChunkRetrieval,
)
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.retrieval.lecture.lecture_transcription_retrieval import (
    LectureTranscriptionRetrieval,
)
from iris.retrieval.lecture.lecture_unit_segment_retrieval import (
    LectureUnitSegmentRetrieval,
)
from iris.retrieval.lecture.lecture_visibility import (
    is_segment_visible,
    is_slide_visible,
    is_transcription_visible,
    is_unit_released,
)
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
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


def lecture_unit(release_date=None, slide_visibility=None):
    return {
        LectureUnitSchema.BASE_URL.value: "https://artemis.example",
        LectureUnitSchema.LECTURE_UNIT_ID.value: 10,
        LectureUnitSchema.COURSE_NAME.value: "Course",
        LectureUnitSchema.LECTURE_NAME.value: "Lecture",
        LectureUnitSchema.LECTURE_UNIT_NAME.value: "Unit",
        LectureUnitSchema.RELEASE_DATE.value: release_date,
        LectureUnitSchema.SLIDE_VISIBILITY.value: slide_visibility,
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
        LectureTranscriptionSchema.PAGE_NUMBER.value: -1,
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


def test_hidden_slide_transcription_is_filtered_across_retrieval_paths():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    props = {
        LectureTranscriptionSchema.SEGMENT_TEXT.value: "Hidden transcript",
        LectureTranscriptionSchema.SEGMENT_SUMMARY.value: "Hidden summary",
        LectureTranscriptionSchema.LECTURE_UNIT_ID.value: 10,
        LectureTranscriptionSchema.BASE_URL.value: "https://artemis.example",
        LectureTranscriptionSchema.COURSE_ID.value: 30,
        LectureTranscriptionSchema.LECTURE_ID.value: 20,
        LectureTranscriptionSchema.SEGMENT_START_TIME.value: 12.0,
        LectureTranscriptionSchema.PAGE_NUMBER.value: 8,
    }
    unit = lecture_unit(slide_visibility=f'{{"2": "{future.isoformat()}", "3": null}}')
    associated_hidden_slide = {
        LectureUnitPageChunkSchema.PAGE_NUMBER.value: 2,
        LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 8,
        LectureUnitPageChunkSchema.HIDDEN_UNTIL.value: future,
    }
    associated_visible_overlay = {
        LectureUnitPageChunkSchema.PAGE_NUMBER.value: 3,
        LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 8,
        LectureUnitPageChunkSchema.HIDDEN_UNTIL.value: None,
    }
    associated_slides = [associated_hidden_slide, associated_visible_overlay]

    assert not is_transcription_visible(props, unit, associated_slides)
    assert (
        LectureGlobalSearchRetrieval._transcription_to_dto(
            props,
            {("https://artemis.example", 10): unit},
            {("https://artemis.example", 10, 8): associated_slides},
        )
        is None
    )

    retrieval = LectureTranscriptionRetrieval.__new__(LectureTranscriptionRetrieval)
    retrieval._lecture_unit_cache = {(30, 20, 10, "https://artemis.example"): unit}
    retrieval._slide_visibility_cache = {}
    retrieval.lecture_unit_page_chunk_collection = Mock()
    retrieval.lecture_unit_page_chunk_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(properties=associated_visible_overlay),
        SimpleNamespace(properties=associated_hidden_slide),
    ]
    assert retrieval.generate_retrieval_dtos(props, "transcription-uuid") is None


def test_transcription_display_page_mapping_does_not_hide_unrelated_visible_slide():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    props = {LectureTranscriptionSchema.PAGE_NUMBER.value: 8}
    unit = lecture_unit(slide_visibility=f'{{"2": null, "3": "{future.isoformat()}"}}')
    associated_visible_slide = {
        LectureUnitPageChunkSchema.PAGE_NUMBER.value: 2,
        LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 8,
        LectureUnitPageChunkSchema.HIDDEN_UNTIL.value: None,
    }

    assert is_transcription_visible(props, unit, associated_visible_slide)


def test_segment_enrichment_does_not_reintroduce_hidden_overlay_transcription():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    transcription_properties = {
        LectureTranscriptionSchema.COURSE_ID.value: 30,
        LectureTranscriptionSchema.LECTURE_ID.value: 20,
        LectureTranscriptionSchema.LECTURE_UNIT_ID.value: 10,
        LectureTranscriptionSchema.BASE_URL.value: "https://artemis.example",
        LectureTranscriptionSchema.PAGE_NUMBER.value: 8,
        LectureTranscriptionSchema.LANGUAGE.value: "en",
        LectureTranscriptionSchema.SEGMENT_START_TIME.value: 12.0,
        LectureTranscriptionSchema.SEGMENT_END_TIME.value: 18.0,
        LectureTranscriptionSchema.SEGMENT_SUMMARY.value: "Hidden summary",
        LectureTranscriptionSchema.SEGMENT_TEXT.value: "Hidden transcript",
    }
    unit = lecture_unit(slide_visibility=f'{{"2": "{future.isoformat()}", "3": null}}')
    unit.update(
        {
            LectureUnitSchema.COURSE_DESCRIPTION.value: "Description",
            LectureUnitSchema.VIDEO_LINK.value: "https://video.example",
        }
    )
    hidden_slide = {
        LectureUnitPageChunkSchema.PAGE_NUMBER.value: 2,
        LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 8,
        LectureUnitPageChunkSchema.HIDDEN_UNTIL.value: future,
    }
    visible_overlay = {
        LectureUnitPageChunkSchema.PAGE_NUMBER.value: 3,
        LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: 8,
        LectureUnitPageChunkSchema.HIDDEN_UNTIL.value: None,
    }
    transcription_pipeline = LectureTranscriptionRetrieval.__new__(
        LectureTranscriptionRetrieval
    )
    transcription_pipeline._lecture_unit_cache = {
        (30, 20, 10, "https://artemis.example"): unit
    }
    transcription_pipeline._slide_visibility_cache = {}
    transcription_pipeline.lecture_unit_page_chunk_collection = Mock()
    transcription_pipeline.lecture_unit_page_chunk_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(properties=visible_overlay),
        SimpleNamespace(properties=hidden_slide),
    ]

    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval.lecture_transcription_pipeline = transcription_pipeline
    retrieval.lecture_transcription_collection = Mock()
    retrieval.lecture_transcription_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="transcription-uuid", properties=transcription_properties)
    ]
    segment = SimpleNamespace(
        uuid="segment-uuid",
        course_id=30,
        lecture_id=20,
        lecture_unit_id=10,
        display_page_number=8,
        page_number=3,
        base_url="https://artemis.example",
    )

    assert not retrieval.get_lecture_transcription_of_lecture_unit(segment)


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
    assert db.lectures.query.fetch_objects.call_args.kwargs["limit"] == 100
    assert db.lectures.query.fetch_objects.call_args.kwargs["offset"] == 0
    assert db.lecture_units.query.fetch_objects.call_args.kwargs["limit"] == 10_000


def test_mcq_content_pages_past_hidden_candidates_and_respects_character_budget(
    monkeypatch,
):
    monkeypatch.setattr(mcq_chat_mixin, "_MCQ_CHUNK_PAGE_SIZE", 1)
    monkeypatch.setattr(mcq_chat_mixin, "_MAX_MCQ_CONTENT_CHARS", 100)
    db = SimpleNamespace(lectures=Mock(), lecture_units=Mock())
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.lectures.query.fetch_objects.side_effect = [
        SimpleNamespace(
            objects=[
                SimpleNamespace(
                    properties={
                        "lecture_unit_id": 10,
                        "lecture_id": 20,
                        "page_number": 1,
                        "page_text_content": "Hidden",
                        "hidden_until": future,
                        "base_url": "https://artemis.example",
                    }
                )
            ]
        ),
        SimpleNamespace(
            objects=[
                SimpleNamespace(
                    properties={
                        "lecture_unit_id": 10,
                        "lecture_id": 20,
                        "page_number": 2,
                        "page_text_content": "V" * 500,
                        "hidden_until": None,
                        "base_url": "https://artemis.example",
                    }
                )
            ]
        ),
    ]
    db.lecture_units.query.fetch_objects.return_value.objects = [
        SimpleNamespace(
            properties={
                "lecture_unit_id": 10,
                "lecture_name": "Lecture",
                "lecture_unit_name": "Unit",
                "release_date": None,
                "base_url": "https://artemis.example",
            }
        )
    ]

    content, units = retrieve_lecture_content_for_mcq(
        db, 30, "https://artemis.example", allow_lecture_tool=True
    )

    assert content is not None
    assert len(content) == 100
    assert [
        call.kwargs["offset"] for call in db.lectures.query.fetch_objects.call_args_list
    ] == [
        0,
        1,
    ]
    assert [unit["lecture_unit_id"] for unit in units] == [10]


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


@pytest.mark.parametrize(
    ("retrieval_type", "filter_module", "collection_attribute"),
    [
        (
            LecturePageChunkRetrieval,
            "iris.retrieval.lecture.lecture_page_chunk_retrieval.Filter",
            "lecture_unit_page_chunk_collection",
        ),
        (
            LectureTranscriptionRetrieval,
            "iris.retrieval.lecture.lecture_transcription_retrieval.Filter",
            "collection",
        ),
    ],
)
def test_lecture_search_combines_course_lecture_unit_and_base_url_filters(
    retrieval_type, filter_module, collection_attribute
):
    retrieval = retrieval_type.__new__(retrieval_type)
    collection = Mock()
    collection.query.hybrid.return_value = SimpleNamespace(objects=[])
    setattr(retrieval, collection_attribute, collection)
    course_builder, lecture_builder, unit_builder, base_url_builder = (
        Mock(),
        Mock(),
        Mock(),
        Mock(),
    )
    course_filter, lecture_filter, unit_filter, base_url_filter = (
        Mock(),
        Mock(),
        Mock(),
        Mock(),
    )
    combined_course_lecture, combined_with_unit, combined_all = Mock(), Mock(), Mock()
    course_builder.equal.return_value = course_filter
    lecture_builder.equal.return_value = lecture_filter
    unit_builder.equal.return_value = unit_filter
    base_url_builder.equal.return_value = base_url_filter
    course_filter.__and__ = Mock(return_value=combined_course_lecture)
    combined_course_lecture.__and__ = Mock(return_value=combined_with_unit)
    combined_with_unit.__and__ = Mock(return_value=combined_all)

    with patch(filter_module) as filter_class:
        filter_class.by_property.side_effect = [
            course_builder,
            lecture_builder,
            unit_builder,
            base_url_builder,
        ]
        retrieval.search_in_db(
            query="query",
            hybrid_factor=0.9,
            result_limit=1,
            lecture_unit_dto=SimpleNamespace(
                course_id=30,
                lecture_id=20,
                lecture_unit_id=10,
                base_url="https://artemis.example",
            ),
            query_vector=[0.1],
        )

    assert collection.query.hybrid.call_args.kwargs["filters"] is combined_all


def test_lecture_unit_lookup_pages_past_unreleased_candidates():
    retrieval = LectureRetrieval.__new__(LectureRetrieval)
    retrieval.lecture_unit_collection = Mock()
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    unreleased = [
        SimpleNamespace(uuid=f"future-{index}", properties={"release_date": future})
        for index in range(100)
    ]
    released = SimpleNamespace(uuid="released", properties={"release_date": None})
    retrieval.lecture_unit_collection.query.fetch_objects.side_effect = [
        SimpleNamespace(objects=unreleased),
        SimpleNamespace(objects=[released]),
    ]

    result = retrieval._fetch_first_released_unit(Mock())

    assert result is released
    assert [
        call.kwargs["offset"]
        for call in retrieval.lecture_unit_collection.query.fetch_objects.call_args_list
    ] == [0, 100]


def test_segment_search_accumulates_scope_filters_and_stops_at_candidate_ceiling():
    retrieval = LectureUnitSegmentRetrieval.__new__(LectureUnitSegmentRetrieval)
    retrieval.llm_embedding = Mock()
    retrieval.llm_embedding.embed.return_value = [0.1]
    retrieval.collection = Mock()
    retrieval.generate_retrieval_dtos = Mock(return_value=None)

    def hidden_page(**kwargs):
        offset = kwargs["offset"]
        return SimpleNamespace(
            objects=[
                SimpleNamespace(uuid=f"{offset}-{index}", properties={})
                for index in range(kwargs["limit"])
            ]
        )

    retrieval.collection.query.hybrid.side_effect = hidden_page
    dto = SimpleNamespace(
        course_id=30,
        lecture_id=20,
        lecture_unit_id=10,
        base_url="https://artemis.example",
    )

    assert not retrieval.search_in_db(dto, "query", 0.9, 4000)

    calls = retrieval.collection.query.hybrid.call_args_list
    assert [call.kwargs["offset"] for call in calls] == [0, 4000, 8000]
    assert [call.kwargs["limit"] for call in calls] == [4000, 4000, 2000]

    def filter_targets(filter_value):
        targets = []
        target = getattr(filter_value, "target", None)
        if target is not None:
            targets.append(target)
        for nested_filter in getattr(filter_value, "filters", []):
            targets.extend(filter_targets(nested_filter))
        return targets

    assert set(filter_targets(calls[0].kwargs["filters"])) == {
        "course_id",
        "lecture_id",
        "lecture_unit_id",
        "base_url",
    }


def test_global_search_expands_candidates_until_visible_result_is_found():
    retrieval = LectureGlobalSearchRetrieval.__new__(LectureGlobalSearchRetrieval)
    hidden = SimpleNamespace()
    visible = SimpleNamespace()
    retrieval._search_segments = Mock(side_effect=[[hidden], [hidden, visible]])
    retrieval._search_video_transcriptions = Mock(side_effect=[[], []])
    visible_dto = SimpleNamespace(
        lecture_unit=SimpleNamespace(source_type="lecture_unit_slide")
    )
    retrieval._map_search_objects = Mock(side_effect=[[], [(1.0, visible_dto)]])

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
    low_score_segment = SimpleNamespace(
        lecture_unit=SimpleNamespace(source_type="lecture_unit_slide")
    )
    high_score_transcription = SimpleNamespace(
        lecture_unit=SimpleNamespace(source_type="lecture_unit_video")
    )
    retrieval._map_search_objects = Mock(
        side_effect=[
            [(0.2, low_score_segment)],
            [(0.2, low_score_segment), (0.9, high_score_transcription)],
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
