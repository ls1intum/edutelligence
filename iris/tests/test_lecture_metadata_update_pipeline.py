"""Contract tests for lightweight lecture metadata updates."""

# pylint: disable=import-outside-toplevel

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from iris.domain.ingestion.lecture_metadata_update_dto import (
    LectureUnitMetadataUpdateDTO,
)
from iris.pipeline.lecture_metadata_update_pipeline import (
    LectureMetadataUpdatePipeline,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.web.routers.webhooks import lecture_metadata_webhook


def metadata_dto() -> LectureUnitMetadataUpdateDTO:
    return LectureUnitMetadataUpdateDTO.model_validate(
        {
            "lectureUnitId": 10,
            "lectureUnitName": "New Unit",
            "lectureUnitLink": "https://artemis.example/units/10",
            "lectureId": 20,
            "lectureName": "Lecture",
            "courseId": 30,
            "courseName": "Course",
            "courseDescription": "Description",
            "videoLink": "https://video.example/watch",
            "baseUrl": "https://artemis.example",
        }
    )


def test_metadata_update_dto_accepts_artemis_aliases():
    dto = metadata_dto()

    assert dto.lecture_unit_id == 10
    assert dto.lecture_unit_name == "New Unit"
    assert dto.base_url == "https://artemis.example"


def test_metadata_update_dto_defaults_omitted_optional_strings_to_empty():
    dto = LectureUnitMetadataUpdateDTO.model_validate(
        {
            "lectureUnitId": 10,
            "lectureId": 20,
            "courseId": 30,
            "baseUrl": "https://artemis.example",
        }
    )

    assert dto.course_description == ""
    assert dto.video_link == ""


def test_metadata_pipeline_updates_existing_objects_without_vectors():
    collection = Mock()
    collection.query.fetch_objects.return_value.objects = [
        SimpleNamespace(uuid="unit-uuid-1"),
        SimpleNamespace(uuid="unit-uuid-2"),
    ]

    updated = LectureMetadataUpdatePipeline(collection)(metadata_dto())

    assert updated == 2
    expected_properties = {
        LectureUnitSchema.COURSE_NAME.value: "Course",
        LectureUnitSchema.COURSE_DESCRIPTION.value: "Description",
        LectureUnitSchema.LECTURE_NAME.value: "Lecture",
        LectureUnitSchema.LECTURE_UNIT_NAME.value: "New Unit",
        LectureUnitSchema.LECTURE_UNIT_LINK.value: "https://artemis.example/units/10",
        LectureUnitSchema.VIDEO_LINK.value: "https://video.example/watch",
    }
    assert collection.data.update.call_count == 2
    collection.data.update.assert_any_call(
        uuid="unit-uuid-1", properties=expected_properties
    )
    collection.data.update.assert_any_call(
        uuid="unit-uuid-2", properties=expected_properties
    )
    for call in collection.data.update.call_args_list:
        assert "vector" not in call.kwargs


def test_metadata_pipeline_missing_object_is_safe_and_retryable():
    collection = Mock()
    collection.query.fetch_objects.return_value.objects = []

    assert LectureMetadataUpdatePipeline(collection)(metadata_dto()) == 0
    collection.data.update.assert_not_called()


def test_metadata_endpoint_returns_not_found_when_ingestion_has_not_created_unit():
    with (
        patch("iris.web.routers.webhooks.VectorDatabase") as database,
        patch("iris.web.routers.webhooks.init_lecture_unit_schema") as init_collection,
        patch("iris.web.routers.webhooks.LectureMetadataUpdatePipeline") as pipeline,
    ):
        init_collection.return_value = Mock()
        pipeline.return_value.return_value = 0

        with pytest.raises(HTTPException) as exc_info:
            lecture_metadata_webhook(metadata_dto())

    assert exc_info.value.status_code == 404
    database.assert_called_once_with()


def test_metadata_webhook_route_matches_artemis_contract():
    from iris.web.routers.webhooks import router

    route = next(route for route in router.routes if route.path.endswith("/metadata"))
    assert route.path == "/api/v1/webhooks/lectures/metadata"
    assert route.methods == {"POST"}
    assert route.status_code == 202
