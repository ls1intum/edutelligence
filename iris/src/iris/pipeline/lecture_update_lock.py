import threading
from contextlib import contextmanager
from typing import Iterator
from weakref import WeakValueDictionary

LectureUpdateKey = tuple[str, int, int, int]

_registry_guard = threading.Lock()
_locks: WeakValueDictionary[LectureUpdateKey, threading.Lock] = WeakValueDictionary()


@contextmanager
def lecture_update_lock(
    base_url: str, course_id: int, lecture_id: int, lecture_unit_id: int
) -> Iterator[None]:
    """Serialize content, metadata, and visibility writes for one lecture unit."""
    key = (base_url, course_id, lecture_id, lecture_unit_id)
    with _registry_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
    with lock:
        yield
