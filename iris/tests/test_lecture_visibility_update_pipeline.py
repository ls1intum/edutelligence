"""Contract and race regression tests for lecture visibility updates."""

# pylint: disable=import-outside-toplevel,protected-access

from datetime import datetime, timezone
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from weaviate.classes.config import Property
from weaviate.collections.classes.config import DataType
from weaviate.exceptions import WeaviateInvalidInputError

from iris.domain.ingestion.lecture_visibility_update_dto import (
    LectureUnitVisibilityUpdateDTO,
)
from iris.pipeline.lecture_ingestion_pipeline import (
    LectureUnitPageIngestionPipeline,
    create_page_data,
)
from iris.pipeline.lecture_unit_pipeline import LectureUnitPipeline
from iris.pipeline.lecture_update_lock import lecture_update_lock
from iris.pipeline.lecture_visibility_update_pipeline import (
    LectureVisibilityUpdatePipeline,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    _add_property_if_missing,
    init_lecture_unit_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)
from iris.web.routers.webhooks import lecture_visibility_webhook


def visibility_dto() -> LectureUnitVisibilityUpdateDTO:
    return LectureUnitVisibilityUpdateDTO.model_validate(
        {
            "lectureUnitId": 10,
            "lectureId": 20,
            "courseId": 30,
            "baseUrl": "https://artemis.example",
            "releaseDate": "2026-07-04T12:00:00+00:00",
            "slides": [
                {
                    "slideNumber": 1,
                    "hiddenUntil": "2026-07-03T12:00:00+00:00",
                }
            ],
        }
    )


def test_visibility_update_dto_accepts_artemis_aliases():
    dto = visibility_dto()

    assert dto.lecture_unit_id == 10
    assert dto.slides[0].slide_number == 1
    assert dto.slides[0].hidden_until == datetime(
        2026, 7, 3, 12, 0, tzinfo=timezone.utc
    )


def test_visibility_update_dto_rejects_naive_dates_and_invalid_slide_numbers():
    with pytest.raises(ValidationError):
        LectureUnitVisibilityUpdateDTO.model_validate(
            {
                "lectureUnitId": 10,
                "lectureId": 20,
                "courseId": 30,
                "baseUrl": "https://artemis.example",
                "releaseDate": "2026-07-04T12:00:00",
                "slides": [{"slideNumber": 0}],
            }
        )


def test_visibility_webhook_route_documents_missing_ingestion():
    from iris.web.routers.webhooks import router

    route = next(route for route in router.routes if route.path.endswith("/visibility"))

    assert route.responses[404]["description"] == "Lecture unit has not been ingested"


def test_visibility_schema_fields_are_defined():
    assert LectureUnitPageChunkSchema.HIDDEN_UNTIL.value == "hidden_until"
    assert LectureUnitSegmentSchema.HIDDEN_UNTIL.value == "hidden_until"
    assert LectureUnitSchema.RELEASE_DATE.value == "release_date"
    assert LectureUnitSchema.SLIDE_VISIBILITY.value == "slide_visibility"


@pytest.mark.parametrize(
    ("initializer", "property_name"),
    [
        (init_lecture_unit_schema, LectureUnitSchema.RELEASE_DATE.value),
        (
            init_lecture_unit_page_chunk_schema,
            LectureUnitPageChunkSchema.HIDDEN_UNTIL.value,
        ),
        (
            init_lecture_unit_segment_schema,
            LectureUnitSegmentSchema.HIDDEN_UNTIL.value,
        ),
    ],
)
def test_existing_collections_receive_visibility_schema_migrations(
    initializer, property_name
):
    client = Mock()
    client.collections.exists.return_value = True
    collection = client.collections.get.return_value
    collection.config.get.return_value.properties = []

    assert initializer(client) is collection

    added_properties = {
        call.args[0].name for call in collection.config.add_property.call_args_list
    }
    assert property_name in added_properties


def test_visibility_pipeline_updates_unit_page_chunks_and_segments_without_vectors():
    unit_collection = Mock()
    unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="unit-uuid")
    ]
    page_collection = Mock()
    page_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="page-uuid-1"),
        SimpleNamespace(uuid="page-uuid-2"),
    ]
    segment_collection = Mock()
    segment_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="segment-uuid")
    ]

    result = LectureVisibilityUpdatePipeline(
        page_collection, unit_collection, segment_collection
    )(visibility_dto())

    assert result.lecture_units_updated == 1
    assert result.page_chunks_updated == 2
    assert result.segments_updated == 1
    assert unit_collection.data.update.call_count == 2
    barrier_update = unit_collection.data.update.call_args_list[0]
    assert barrier_update.kwargs["uuid"] == "unit-uuid"
    assert barrier_update.kwargs["properties"][
        LectureUnitSchema.RELEASE_DATE.value
    ] == datetime.max.replace(tzinfo=timezone.utc)
    assert (
        barrier_update.kwargs["properties"][LectureUnitSchema.SLIDE_VISIBILITY.value]
        == '{"1": "2026-07-03T12:00:00+00:00"}'
    )
    unit_collection.data.update.assert_called_with(
        uuid="unit-uuid",
        properties={
            LectureUnitSchema.RELEASE_DATE.value: datetime(
                2026, 7, 4, 12, 0, tzinfo=timezone.utc
            )
        },
    )
    expected_hidden = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    page_collection.data.update.assert_any_call(
        uuid="page-uuid-1",
        properties={LectureUnitPageChunkSchema.HIDDEN_UNTIL.value: expected_hidden},
    )
    segment_collection.data.update.assert_called_once_with(
        uuid="segment-uuid",
        properties={LectureUnitSegmentSchema.HIDDEN_UNTIL.value: expected_hidden},
    )
    for collection in (unit_collection, page_collection, segment_collection):
        for call in collection.data.update.call_args_list:
            assert "vector" not in call.kwargs


def test_visibility_pipeline_is_idempotent_when_slide_objects_are_missing():
    unit_collection = Mock()
    unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="unit-uuid")
    ]
    page_collection = Mock()
    page_collection.query.fetch_objects.return_value.objects = []
    segment_collection = Mock()
    segment_collection.query.fetch_objects.return_value.objects = []

    result = LectureVisibilityUpdatePipeline(
        page_collection, unit_collection, segment_collection
    )(visibility_dto())

    assert result.lecture_units_updated == 1
    assert result.page_chunks_updated == 0
    assert result.segments_updated == 0
    page_collection.data.update.assert_not_called()
    segment_collection.data.update.assert_not_called()


def test_release_only_visibility_update_preserves_existing_hidden_slides():
    unit_collection = Mock()
    unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(
            uuid="unit-uuid",
            properties={
                LectureUnitSchema.SLIDE_VISIBILITY.value: (
                    '{"1": "2099-01-01T00:00:00+00:00"}'
                )
            },
        )
    ]
    page_collection = Mock()
    segment_collection = Mock()
    dto = visibility_dto().model_copy(update={"slides": []})

    result = LectureVisibilityUpdatePipeline(
        page_collection, unit_collection, segment_collection
    )(dto)

    assert result.page_chunks_updated == 0
    assert result.segments_updated == 0
    barrier_properties = unit_collection.data.update.call_args_list[0].kwargs[
        "properties"
    ]
    assert (
        barrier_properties[LectureUnitSchema.SLIDE_VISIBILITY.value]
        == '{"1": "2099-01-01T00:00:00+00:00"}'
    )


def test_partial_visibility_update_merges_with_existing_slide_snapshot():
    unit_collection = Mock()
    unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(
            uuid="unit-uuid",
            properties={LectureUnitSchema.SLIDE_VISIBILITY.value: '{"2": null}'},
        )
    ]
    page_collection = Mock()
    page_collection.query.fetch_objects.return_value.objects = []
    segment_collection = Mock()
    segment_collection.query.fetch_objects.return_value.objects = []

    LectureVisibilityUpdatePipeline(
        page_collection, unit_collection, segment_collection
    )(visibility_dto())

    barrier_properties = unit_collection.data.update.call_args_list[0].kwargs[
        "properties"
    ]
    assert (
        barrier_properties[LectureUnitSchema.SLIDE_VISIBILITY.value]
        == '{"1": "2026-07-03T12:00:00+00:00", "2": null}'
    )


def test_visibility_pipeline_keeps_unit_denied_when_slide_update_fails():
    unit_collection = Mock()
    unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="unit-uuid")
    ]
    page_collection = Mock()
    page_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="page-uuid")
    ]
    page_collection.data.update.side_effect = RuntimeError("Weaviate write failed")
    segment_collection = Mock()

    with pytest.raises(RuntimeError, match="Weaviate write failed"):
        LectureVisibilityUpdatePipeline(
            page_collection, unit_collection, segment_collection
        )(visibility_dto())

    assert unit_collection.data.update.call_count == 1
    assert unit_collection.data.update.call_args.kwargs["properties"][
        LectureUnitSchema.RELEASE_DATE.value
    ] == datetime.max.replace(tzinfo=timezone.utc)


def test_missing_unit_does_not_partially_update_orphaned_slide_objects():
    unit_collection = Mock()
    unit_collection.query.fetch_objects.return_value.objects = []
    page_collection = Mock()
    segment_collection = Mock()

    result = LectureVisibilityUpdatePipeline(
        page_collection, unit_collection, segment_collection
    )(visibility_dto())

    assert result.lecture_units_updated == 0
    page_collection.query.fetch_objects.assert_not_called()
    segment_collection.query.fetch_objects.assert_not_called()


def test_lecture_update_lock_serializes_writes_for_same_unit():
    first_acquired = Event()
    release_first = Event()
    second_acquired = Event()

    def hold_first_lock():
        with lecture_update_lock("base", 1, 2, 3):
            first_acquired.set()
            release_first.wait(timeout=2)

    def acquire_second_lock():
        first_acquired.wait(timeout=2)
        with lecture_update_lock("base", 1, 2, 3):
            second_acquired.set()

    first = Thread(target=hold_first_lock)
    second = Thread(target=acquire_second_lock)
    first.start()
    second.start()
    assert first_acquired.wait(timeout=2)
    assert not second_acquired.wait(timeout=0.05)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert second_acquired.is_set()


def test_full_page_ingestion_data_carries_preserved_visibility():
    hidden_until = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    lecture_unit = SimpleNamespace(
        lecture_id=20,
        lecture_unit_id=10,
        course_id=30,
        attachment_version=4,
    )

    result = create_page_data(
        0,
        [SimpleNamespace(page_content="Slide content")],
        lecture_unit,
        "en",
        "https://artemis.example",
        1,
        hidden_until,
    )

    assert result[0][LectureUnitPageChunkSchema.HIDDEN_UNTIL.value] == hidden_until


def test_full_page_reingestion_loads_existing_visibility_by_page():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    pipeline.collection = Mock()
    pipeline.lecture_unit_collection = Mock()
    pipeline.dto = SimpleNamespace(
        settings=SimpleNamespace(artemis_base_url="https://artemis.example"),
        lecture_unit=SimpleNamespace(course_id=30, lecture_id=20, lecture_unit_id=10),
    )
    pipeline._get_page_chunk_filter = Mock(return_value=Mock())
    hidden_until = datetime(2026, 7, 3, 12, 0, tzinfo=timezone.utc)
    pipeline.lecture_unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(
            properties={
                LectureUnitSchema.SLIDE_VISIBILITY.value: (
                    '{"1": "2026-07-03T12:00:00+00:00"}'
                )
            }
        )
    ]

    pipeline._load_existing_slide_visibility()

    assert pipeline._hidden_until_by_page == {1: hidden_until}


def test_full_unit_reingestion_preserves_visibility_but_uses_fresh_content_metadata():
    pipeline = LectureUnitPipeline.__new__(LectureUnitPipeline)
    pipeline.weaviate_client = Mock()
    pipeline.local = False
    pipeline.callback = None
    pipeline.llm_embedding = Mock()
    pipeline.llm_embedding.embed.return_value = [0.1]
    pipeline.lecture_unit_collection = Mock()
    release_date = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    stored_properties = {
        LectureUnitSchema.RELEASE_DATE.value: release_date,
        LectureUnitSchema.SLIDE_VISIBILITY.value: '{"2": null}',
        LectureUnitSchema.LECTURE_UNIT_NAME.value: "Stale Unit Name",
        LectureUnitSchema.LECTURE_UNIT_LINK.value: "stale-unit-link",
        LectureUnitSchema.VIDEO_LINK.value: "stale-video-link",
    }
    pipeline.lecture_unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(properties=stored_properties)
    ]
    lecture_unit = SimpleNamespace(
        course_id=30,
        course_name="Course",
        course_description="Description",
        lecture_id=20,
        lecture_name="Lecture",
        lecture_unit_id=10,
        lecture_unit_name="Fresh Unit Name",
        lecture_unit_link="https://artemis.example/unit/10",
        video_link="https://video.example/fresh",
        base_url="https://artemis.example",
        lecture_unit_summary="",
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_summary,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as unit_summary,
    ):
        segment_summary.return_value.return_value = (["Segment"], [])
        unit_summary.return_value.return_value = ("Unit summary", [])
        pipeline(lecture_unit)

    inserted_properties = pipeline.lecture_unit_collection.data.insert.call_args.kwargs[
        "properties"
    ]
    assert inserted_properties[LectureUnitSchema.RELEASE_DATE.value] == release_date
    assert (
        inserted_properties[LectureUnitSchema.SLIDE_VISIBILITY.value] == '{"2": null}'
    )
    assert inserted_properties[LectureUnitSchema.LECTURE_UNIT_NAME.value] == (
        "Fresh Unit Name"
    )
    assert (
        inserted_properties[LectureUnitSchema.LECTURE_UNIT_LINK.value]
        == "https://artemis.example/unit/10"
    )
    assert inserted_properties[LectureUnitSchema.VIDEO_LINK.value] == (
        "https://video.example/fresh"
    )


def test_full_unit_reingestion_preserves_metadata_updated_after_ingestion_started():
    pipeline = LectureUnitPipeline.__new__(LectureUnitPipeline)
    pipeline.weaviate_client = Mock()
    pipeline.local = False
    pipeline.callback = None
    pipeline.llm_embedding = Mock()
    pipeline.llm_embedding.embed.return_value = [0.1]
    pipeline.lecture_unit_collection = Mock()
    old_properties = {
        LectureUnitSchema.LECTURE_UNIT_LINK.value: "old-link",
        LectureUnitSchema.RELEASE_DATE.value: None,
    }
    new_properties = {
        LectureUnitSchema.LECTURE_UNIT_LINK.value: "concurrent-metadata-link",
        LectureUnitSchema.RELEASE_DATE.value: None,
    }
    pipeline.lecture_unit_collection.query.fetch_objects.return_value = SimpleNamespace(
        objects=[SimpleNamespace(properties=new_properties)]
    )
    lecture_unit = SimpleNamespace(
        course_id=30,
        course_name="Course",
        course_description="Description",
        lecture_id=20,
        lecture_name="Lecture",
        lecture_unit_id=10,
        lecture_unit_name="Unit",
        lecture_unit_link="content-ingestion-link",
        video_link="",
        base_url="https://artemis.example",
        lecture_unit_summary="",
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_summary,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as unit_summary,
    ):
        segment_summary.return_value.return_value = (["Segment"], [])
        unit_summary.return_value.return_value = ("Unit summary", [])
        pipeline(lecture_unit, initial_properties=old_properties)

    inserted_properties = pipeline.lecture_unit_collection.data.insert.call_args.kwargs[
        "properties"
    ]
    assert (
        inserted_properties[LectureUnitSchema.LECTURE_UNIT_LINK.value]
        == "concurrent-metadata-link"
    )


def test_full_unit_reingestion_does_not_delete_existing_unit_when_embedding_fails():
    pipeline = LectureUnitPipeline.__new__(LectureUnitPipeline)
    pipeline.weaviate_client = Mock()
    pipeline.local = False
    pipeline.callback = None
    pipeline.llm_embedding = Mock()
    pipeline.llm_embedding.embed.side_effect = RuntimeError("embedding failed")
    pipeline.lecture_unit_collection = Mock()
    pipeline.lecture_unit_collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(properties={})
    ]
    lecture_unit = SimpleNamespace(
        course_id=30,
        course_name="Course",
        course_description="Description",
        lecture_id=20,
        lecture_name="Lecture",
        lecture_unit_id=10,
        lecture_unit_name="Unit",
        lecture_unit_link="https://artemis.example/unit/10",
        video_link="",
        base_url="https://artemis.example",
        lecture_unit_summary="",
    )

    with (
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSegmentSummaryPipeline"
        ) as segment_summary,
        patch(
            "iris.pipeline.lecture_unit_pipeline.LectureUnitSummaryPipeline"
        ) as unit_summary,
    ):
        segment_summary.return_value.return_value = (["Segment"], [])
        unit_summary.return_value.return_value = ("Unit summary", [])
        with pytest.raises(RuntimeError, match="embedding failed"):
            pipeline(lecture_unit)

    pipeline.lecture_unit_collection.data.delete_many.assert_not_called()
    pipeline.lecture_unit_collection.data.insert.assert_not_called()


def test_concurrent_lecture_schema_property_add_is_treated_as_idempotent():
    collection = Mock()
    new_property = Property(
        name=LectureUnitSchema.RELEASE_DATE.value,
        data_type=DataType.DATE,
    )
    collection.config.get.side_effect = [
        SimpleNamespace(properties=[]),
        SimpleNamespace(
            properties=[SimpleNamespace(name=LectureUnitSchema.RELEASE_DATE.value)]
        ),
    ]
    collection.config.add_property.side_effect = WeaviateInvalidInputError(
        "property already exists"
    )

    _add_property_if_missing(collection, new_property)


@pytest.mark.parametrize(
    ("initializer", "property_name"),
    [
        (
            init_lecture_unit_page_chunk_schema,
            LectureUnitPageChunkSchema.HIDDEN_UNTIL.value,
        ),
        (
            init_lecture_unit_segment_schema,
            LectureUnitSegmentSchema.HIDDEN_UNTIL.value,
        ),
    ],
)
def test_concurrent_visibility_property_add_is_treated_as_idempotent(
    initializer, property_name
):
    client = Mock()
    client.collections.exists.return_value = True
    collection = client.collections.get.return_value
    existing_properties = [
        SimpleNamespace(name=LectureUnitPageChunkSchema.COURSE_LANGUAGE.value),
        SimpleNamespace(name=LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value),
    ]
    collection.config.get.side_effect = [
        SimpleNamespace(properties=existing_properties),
        SimpleNamespace(properties=[]),
        SimpleNamespace(properties=[SimpleNamespace(name=property_name)]),
    ]
    collection.config.add_property.side_effect = WeaviateInvalidInputError(
        "property already exists"
    )

    assert initializer(client) is collection


def test_lecture_schema_property_add_propagates_unrelated_invalid_input():
    collection = Mock()
    new_property = Property(
        name=LectureUnitSchema.RELEASE_DATE.value,
        data_type=DataType.DATE,
    )
    collection.config.get.side_effect = [
        SimpleNamespace(properties=[]),
        SimpleNamespace(properties=[]),
    ]
    collection.config.add_property.side_effect = WeaviateInvalidInputError(
        "invalid property definition"
    )

    with pytest.raises(WeaviateInvalidInputError, match="invalid property definition"):
        _add_property_if_missing(collection, new_property)


def test_visibility_endpoint_returns_not_found_when_ingestion_has_not_created_unit():
    with (
        patch("iris.web.routers.webhooks.VectorDatabase") as database,
        patch(
            "iris.web.routers.webhooks.init_lecture_unit_page_chunk_schema"
        ) as init_pages,
        patch("iris.web.routers.webhooks.init_lecture_unit_schema") as init_units,
        patch(
            "iris.web.routers.webhooks.init_lecture_unit_segment_schema"
        ) as init_segments,
        patch("iris.web.routers.webhooks.LectureVisibilityUpdatePipeline") as pipeline,
    ):
        init_pages.return_value = Mock()
        init_units.return_value = Mock()
        init_segments.return_value = Mock()
        pipeline.return_value.return_value = SimpleNamespace(lecture_units_updated=0)

        with pytest.raises(HTTPException) as exc_info:
            lecture_visibility_webhook(visibility_dto())

    assert exc_info.value.status_code == 404
    database.assert_called_once_with()


def test_visibility_webhook_route_matches_artemis_contract():
    from iris.web.routers.webhooks import router

    route = next(route for route in router.routes if route.path.endswith("/visibility"))
    assert route.path == "/api/v1/webhooks/lectures/visibility"
    assert route.methods == {"POST"}
    assert route.status_code == 202
