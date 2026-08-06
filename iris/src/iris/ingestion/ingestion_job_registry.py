import threading
from contextlib import contextmanager
from threading import Event
from typing import Iterator, Optional
from weakref import WeakValueDictionary

from iris.common.cancellation import raise_if_cancelled
from iris.common.custom_exceptions import IngestionCancelledException
from iris.common.logging_config import get_logger

logger = get_logger(__name__)

IngestionJobKey = tuple[str, int, int, int]

_registry_guard = threading.Lock()
_locks: WeakValueDictionary[IngestionJobKey, threading.Lock] = WeakValueDictionary()
_latest: dict[IngestionJobKey, Event] = {}


def ingestion_job_key(
    base_url: str, course_id: int, lecture_id: int, lecture_unit_id: int
) -> IngestionJobKey:
    return (base_url, course_id, lecture_id, lecture_unit_id)


def _lock_for(key: IngestionJobKey) -> threading.Lock:
    with _registry_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
    return lock


@contextmanager
def ingestion_job_commit_lock(
    base_url: str, course_id: int, lecture_id: int, lecture_unit_id: int
) -> Iterator[None]:
    key = ingestion_job_key(base_url, course_id, lecture_id, lecture_unit_id)
    with _lock_for(key):
        yield


def current_job_cancel_event(
    base_url: str, course_id: int, lecture_id: int, lecture_unit_id: int
) -> Optional[Event]:
    key = ingestion_job_key(base_url, course_id, lecture_id, lecture_unit_id)
    return _latest.get(key)


def set_current_job_cancel_event(
    base_url: str,
    course_id: int,
    lecture_id: int,
    lecture_unit_id: int,
    cancel_event: Event,
) -> None:
    key = ingestion_job_key(base_url, course_id, lecture_id, lecture_unit_id)
    _latest[key] = cancel_event


def clear_current_job_cancel_event(
    base_url: str,
    course_id: int,
    lecture_id: int,
    lecture_unit_id: int,
    cancel_event: Event,
) -> None:
    key = ingestion_job_key(base_url, course_id, lecture_id, lecture_unit_id)
    if _latest.get(key) is cancel_event:
        del _latest[key]


@contextmanager
def ingestion_job_owner_guard(
    *,
    base_url: str,
    course_id: int,
    lecture_id: int,
    lecture_unit_id: int,
    cancel_event: Optional[Event],
    stage: str,
) -> Iterator[None]:
    with ingestion_job_commit_lock(base_url, course_id, lecture_id, lecture_unit_id):
        raise_if_cancelled(cancel_event, lecture_unit_id, stage)
        current_cancel_event = current_job_cancel_event(
            base_url, course_id, lecture_id, lecture_unit_id
        )
        if (
            cancel_event is not None
            and current_cancel_event is not None
            and current_cancel_event is not cancel_event
        ):
            logger.info(
                "[Lecture %s] Ownership lost at %s; aborting stale commit",
                lecture_unit_id,
                stage,
            )
            raise IngestionCancelledException(
                lecture_unit_id,
                f"Cancelled during {stage}",
            )
        yield
