from enum import Enum


class SearchableEntitiesSchema(Enum):
    """
    Property names for the Artemis-managed Weaviate collection.
    The base collection name is ``SearchableEntities``; Artemis may prepend a deployment-specific
    prefix (``artemis.weaviate.collectionPrefix``). Artemis sends the fully-resolved name in
    each request via ``entityCollectionName``, so Iris never has to guess or mirror the prefix.
    These property names must stay in sync with ``SearchableEntitySchema.java`` in Artemis.
    Pyris only reads this collection — Artemis owns ingestion.
    """

    COLLECTION_NAME = "SearchableEntities"

    # Common
    TYPE = "type"
    ENTITY_ID = "entity_id"
    COURSE_ID = "course_id"
    TITLE = "title"
    DESCRIPTION = "description"

    # Access-control filters
    RELEASE_DATE = "release_date"
    IS_EXAM_EXERCISE = "is_exam_exercise"
    EXAM_VISIBLE_DATE = "exam_visible_date"
    EXAM_START_DATE = "exam_start_date"
    EXAM_END_DATE = "exam_end_date"
    TEST_EXAM = "test_exam"
    EXAM_ID = "exam_id"
    VISIBLE_DATE = "visible_date"
    FAQ_STATE = "faq_state"
    CHANNEL_IS_COURSE_WIDE = "channel_is_course_wide"
    CHANNEL_IS_PUBLIC = "channel_is_public"
    COURSE_NAME = "course_name"

    # Type-specific display fields
    SHORT_NAME = "short_name"
    EXERCISE_TYPE = "exercise_type"
    ASSESSMENT_TYPE = "assessment_type"
    DIFFICULTY = "difficulty"
    MAX_POINTS = "max_points"
    START_DATE = "start_date"
    END_DATE = "end_date"
    DUE_DATE = "due_date"
    LECTURE_ID = "lecture_id"
    UNIT_TYPE = "unit_type"


class EntityType:
    """Canonical type discriminator values — must match TypeValues in Artemis."""

    EXERCISE = "exercise"
    LECTURE = "lecture"
    LECTURE_UNIT = "lecture_unit"
    EXAM = "exam"
    FAQ = "faq"
    CHANNEL = "channel"


class FaqState:
    ACCEPTED = "ACCEPTED"
