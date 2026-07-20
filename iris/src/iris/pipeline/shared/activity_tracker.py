import threading
import time
from collections.abc import Callable

from iris.common.logging_config import get_logger
from iris.domain.status.activity_dto import ActivityDTO, ActivityKind, ActivityState

logger = get_logger(__name__)


class ActivityTracker:
    """Thread-safe tracker for live chat activity snapshots."""

    def __init__(self, emit: Callable[[list[ActivityDTO], int], None]):
        self._emit = emit
        self._lock = threading.Lock()
        self._items: list[ActivityDTO] = []
        self._started_at: dict[str, float] = {}
        self._seq = 0

    def start(self, kind: ActivityKind, name: str, detail: str | None = None) -> str:
        with self._lock:
            item_id = f"act-{len(self._items) + 1}"
            self._items.append(
                ActivityDTO(
                    id=item_id,
                    kind=kind,
                    name=name,
                    state=ActivityState.RUNNING,
                    detail=detail,
                )
            )
            self._started_at[item_id] = time.monotonic()
            items, seq = self._bump_and_copy_locked()
        self._emit(items, seq)
        return item_id

    def finish(self, item_id: str, result: str | None = None) -> None:
        self._complete(item_id, ActivityState.FINISHED, result=result)

    def fail(self, item_id: str) -> None:
        self._complete(item_id, ActivityState.FAILED)

    def snapshot(self) -> tuple[list[ActivityDTO], int]:
        with self._lock:
            return self._copy_locked(), self._seq

    def authoritative_snapshot(self) -> tuple[list[ActivityDTO], int]:
        with self._lock:
            items, seq = self._bump_and_copy_locked()
        return items, seq

    def _complete(
        self,
        item_id: str,
        state: ActivityState,
        result: str | None = None,
    ) -> None:
        with self._lock:
            item = self._find_locked(item_id)
            if item is None:
                logger.debug("Ignoring unknown activity item id %s", item_id)
                return
            item.state = state
            item.result = result
            item.duration_millis = self._duration_millis(item_id)
            items, seq = self._bump_and_copy_locked()
        self._emit(items, seq)

    def _find_locked(self, item_id: str) -> ActivityDTO | None:
        for item in self._items:
            if item.id == item_id:
                return item
        return None

    def _duration_millis(self, item_id: str) -> int:
        started_at = self._started_at.get(item_id)
        if started_at is None:
            return 0
        return max(0, int((time.monotonic() - started_at) * 1000))

    def _bump_and_copy_locked(self) -> tuple[list[ActivityDTO], int]:
        self._seq += 1
        return self._copy_locked(), self._seq

    def _copy_locked(self) -> list[ActivityDTO]:
        return [item.model_copy(deep=True) for item in self._items]
