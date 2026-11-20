import json
from enum import Enum
from urllib.parse import unquote

from fastapi import APIRouter, Response, status
from fastapi.params import Query
from weaviate.collections.classes.filters import Filter

from iris.dependencies import AuthorizedKey, require_base_url
from iris.vector_database.instance_filter import artemis_instance_filter

from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_unit_schema import (
    LectureUnitSchema,
)

router = APIRouter(prefix="/api/v1", tags=["ingestion_status"])


class IngestionState(str, Enum):
    DONE = "DONE"
    NOT_STARTED = "NOT_STARTED"


@router.get(
    "/courses/{course_id}/lectures/{lecture_id}/lectureUnits/{lecture_unit_id}/ingestion-state",
)
def get_lecture_unit_ingestion_state(
    api_key: AuthorizedKey,
    course_id: int,
    lecture_id: int,
    lecture_unit_id: int,
    base_url: str = Query(...),
):
    """

    :param course_id:
    :param lecture_id:
    :param lecture_unit_id:
    :param base_url:
    :return:
    """
    decoded_base_url = unquote(base_url)
    require_base_url(api_key, decoded_base_url)
    db = VectorDatabase()
    result = db.lecture_units.query.fetch_objects(
        filters=(
            artemis_instance_filter(LectureUnitSchema, decoded_base_url)
            & Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(course_id)
            & Filter.by_property(LectureUnitSchema.LECTURE_ID.value).equal(lecture_id)
            & Filter.by_property(LectureUnitSchema.LECTURE_UNIT_ID.value).equal(
                lecture_unit_id
            )
        ),
        limit=1,
        return_properties=[LectureUnitSchema.LECTURE_UNIT_ID.value],
    )

    if len(result.objects) > 0:
        return Response(
            status_code=status.HTTP_200_OK,
            content=json.dumps({"state": IngestionState.DONE.value}),
            media_type="application/json",
        )
    else:
        return Response(
            status_code=status.HTTP_200_OK,
            content=json.dumps({"state": IngestionState.NOT_STARTED.value}),
            media_type="application/json",
        )
