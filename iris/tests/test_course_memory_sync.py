"""The nightly sync is the backstop for every update that did not reach Iris.

Artemis sends, per course, the complete list of threads that may have an entry with
their current version and whether they may be stored right now. Whatever does not
match is retracted with a tombstone, so the stored text cannot outlive a deletion, an
opt-out or an edit by more than one sync — and a superseded ingestion that is still
running cannot bring it back.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from iris.domain.ingestion.course_memory_sync_dto import (
    CourseMemoryCourseSyncDTO,
    CourseMemoryInstanceSyncDTO,
)
from iris.pipeline import course_memory_ingestion_pipeline as cm_module
from iris.pipeline.course_memory_ingestion_pipeline import (
    CourseMemoryDeleter,
    CourseMemoryIngestionPipeline,
)
from iris.vector_database.course_memory_schema import CourseMemorySchema

# pylint: disable=protected-access

BASE = "https://artemis.example"
OTHER = "https://other.example"
NOW = datetime(2026, 10, 5, 3, 30, tzinfo=timezone.utc)
LONG_AGO = NOW - timedelta(days=3)


class FakeCollection:
    """Just enough of a Weaviate collection: objects by uuid, a cursor, writes."""

    def __init__(self):
        self.objects = {}
        self.query = SimpleNamespace(fetch_object_by_id=self._fetch)
        self.data = SimpleNamespace(replace=self._write, insert=self._write)

    def _fetch(self, uuid):
        props = self.objects.get(uuid)
        return SimpleNamespace(properties=dict(props)) if props is not None else None

    def _write(self, uuid, properties, vector=None):
        del vector
        self.objects[uuid] = dict(properties)

    def iterator(self, return_properties=None):
        del return_properties
        for uuid, props in list(self.objects.items()):
            yield SimpleNamespace(uuid=uuid, properties=dict(props))

    def put(
        self, post_id, version, *, course_id=7, base_url=BASE, deleted=False, at=None
    ):
        self.objects[cm_module._deterministic_uuid(base_url, post_id, course_id)] = {
            CourseMemorySchema.BASE_URL.value: base_url,
            CourseMemorySchema.COURSE_ID.value: course_id,
            CourseMemorySchema.POST_ID.value: post_id,
            CourseMemorySchema.VERSION.value: version,
            CourseMemorySchema.DELETED.value: deleted,
            CourseMemorySchema.ANSWER.value: "" if deleted else "stored answer",
            CourseMemorySchema.WRITTEN_AT.value: at or LONG_AGO,
        }

    def get(self, post_id, *, course_id=7, base_url=BASE):
        return self.objects[cm_module._deterministic_uuid(base_url, post_id, course_id)]


def _settings(base_url=BASE):
    return {"authenticationToken": "token", "artemisBaseUrl": base_url}


def _course_sync(threads, *, course_id=7, base_url=BASE):
    return CourseMemoryCourseSyncDTO.model_validate(
        {
            "settings": _settings(base_url),
            "snapshotAt": NOW.isoformat(),
            "courseId": course_id,
            "threads": threads,
        }
    )


def _thread(post_id, version, eligible=True):
    return {"postId": post_id, "version": version, "eligible": eligible}


def _deleter(collection):
    return CourseMemoryDeleter.for_collection(collection)


def test_up_to_date_entry_is_kept():
    collection = FakeCollection()
    collection.put("11", 4)

    _deleter(collection).sync_course(_course_sync([_thread(11, 4)]))

    assert collection.get("11")[CourseMemorySchema.DELETED.value] is False


def test_newer_entry_than_the_snapshot_is_kept():
    # A refresh landed after Artemis read its state; the newer write stands.
    collection = FakeCollection()
    collection.put("11", 5)

    _deleter(collection).sync_course(_course_sync([_thread(11, 4)]))

    assert collection.get("11")[CourseMemorySchema.DELETED.value] is False


def test_entry_that_missed_an_update_is_retracted_at_the_artemis_version():
    # Artemis dispatched version 6 (an edit, a deleted reply, an opt-out) and it never
    # landed: the stored text may hold what should be gone.
    collection = FakeCollection()
    collection.put("11", 4)

    _deleter(collection).sync_course(_course_sync([_thread(11, 6)]))

    stored = collection.get("11")
    assert stored[CourseMemorySchema.DELETED.value] is True
    assert stored[CourseMemorySchema.VERSION.value] == 6
    assert stored[CourseMemorySchema.ANSWER.value] == ""


def test_superseded_ingestion_still_running_cannot_restore_the_text():
    # Stored 10, an ingestion with version 11 (old text) still running, Artemis at 12.
    # The tombstone carries 12, so the late 11 is rejected.
    collection = FakeCollection()
    collection.put("11", 10)
    _deleter(collection).sync_course(_course_sync([_thread(11, 12)]))

    late = object.__new__(CourseMemoryIngestionPipeline)
    late.collection = collection
    late.llm_embedding = SimpleNamespace(embed=lambda _: [0.1])
    late.dto = SimpleNamespace(
        course_id=7,
        post_id="11",
        message_id="answer-1",
        conversation_id="3",
        source=cm_module.CourseMemorySource.THREAD_RESOLVED,
        version=11,
        verified_at=None,
        base_url=BASE,
    )
    late.upsert("q", "old text")

    assert collection.get("11")[CourseMemorySchema.DELETED.value] is True
    assert collection.get("11")[CourseMemorySchema.VERSION.value] == 12


def test_entry_of_a_thread_that_may_not_be_stored_is_retracted():
    # Channel made private, exercise hidden again, Iris switched off, root author
    # opted out: the thread is listed as not eligible.
    collection = FakeCollection()
    collection.put("11", 4)

    _deleter(collection).sync_course(_course_sync([_thread(11, 4, eligible=False)]))

    assert collection.get("11")[CourseMemorySchema.DELETED.value] is True
    assert collection.get("11")[CourseMemorySchema.VERSION.value] == 4


def test_tombstone_of_an_ineligible_thread_is_raised_to_the_artemis_version():
    collection = FakeCollection()
    collection.put("11", 4, deleted=True)

    _deleter(collection).sync_course(_course_sync([_thread(11, 7, eligible=False)]))

    assert collection.get("11")[CourseMemorySchema.VERSION.value] == 7


def test_entry_of_a_deleted_thread_is_retracted():
    collection = FakeCollection()
    collection.put("11", 4)

    _deleter(collection).sync_course(_course_sync([]))

    assert collection.get("11")[CourseMemorySchema.DELETED.value] is True
    assert collection.get("11")[CourseMemorySchema.VERSION.value] == 4


def test_entry_written_after_the_snapshot_is_left_alone():
    # First resolved while the sync was running: Artemis did not list it yet.
    collection = FakeCollection()
    collection.put("11", 1, at=NOW + timedelta(minutes=1))

    _deleter(collection).sync_course(_course_sync([]))

    assert collection.get("11")[CourseMemorySchema.DELETED.value] is False


def test_entry_written_just_before_the_snapshot_is_left_alone():
    # The margin absorbs clock skew between Artemis and Iris.
    collection = FakeCollection()
    collection.put("11", 1, at=NOW - timedelta(minutes=2))

    _deleter(collection).sync_course(_course_sync([]))

    assert collection.get("11")[CourseMemorySchema.DELETED.value] is False


def test_other_courses_and_other_instances_are_untouched():
    collection = FakeCollection()
    collection.put("11", 4, course_id=8)
    collection.put("11", 4, base_url=OTHER)

    _deleter(collection).sync_course(_course_sync([]))

    assert collection.get("11", course_id=8)[CourseMemorySchema.DELETED.value] is False
    assert (
        collection.get("11", base_url=OTHER)[CourseMemorySchema.DELETED.value] is False
    )


def test_entries_of_deleted_courses_are_retracted_for_good():
    collection = FakeCollection()
    collection.put("11", 4, course_id=7)
    collection.put("12", 4, course_id=9)
    collection.put("13", 4, course_id=9, base_url=OTHER)
    dto = CourseMemoryInstanceSyncDTO.model_validate(
        {"settings": _settings(), "snapshotAt": NOW.isoformat(), "courseIds": [7]}
    )

    _deleter(collection).sync_instance(dto)

    assert collection.get("11", course_id=7)[CourseMemorySchema.DELETED.value] is False
    deleted_course = collection.get("12", course_id=9)
    assert deleted_course[CourseMemorySchema.DELETED.value] is True
    assert deleted_course[CourseMemorySchema.VERSION.value] == cm_module.FINAL_VERSION
    other = collection.get("13", course_id=9, base_url=OTHER)
    assert other[CourseMemorySchema.DELETED.value] is False
