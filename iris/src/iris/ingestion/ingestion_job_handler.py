"""Sequencing of per-lecture-unit ingestion jobs.

If a second ingestion request arrives for the same lecture unit, the old one is
flagged for cancellation and the new one starts immediately. Job threads are
not serialized here, so the two overlap until the old one reaches a checkpoint.

What keeps the old job from overwriting the new one's content is the
cancellation check placed immediately before *every* Weaviate write. The flag is
set here, synchronously, before the new thread starts — so a superseded job can
never begin another write, only finish one it had already started.

The write-phase locks are not what makes this safe: they prevent two writes from
interleaving, but they impose no order between them. A superseded job that got
the lock last would still write last. Only the check before each write prevents
that, which makes it an invariant every future write site has to honour.
"""

import threading
from threading import Event, Thread
from typing import Dict, Tuple

from iris.common.cancellation import CancellationSignal
from iris.common.logging_config import get_logger

logger = get_logger(__name__)

JobKey = Tuple[int, int, int]


class IngestionJobHandler:
    """Runs one ingestion job per lecture unit, newest request winning."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latest: Dict[JobKey, Event] = {}  # cancel event of newest request

    def create_cancellation_event(self) -> CancellationSignal:
        """Create a cancellation signal to hand to a job and its pipeline."""
        return CancellationSignal()

    def add_job(
        self,
        process: Thread,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event,
    ) -> None:
        """Start ``process``, superseding any request for the same unit."""
        key = (course_id, lecture_id, lecture_unit_id)
        with self._lock:
            superseded = self._latest.get(key)
            if superseded is not None:
                superseded.set()
            self._latest[key] = cancel_event
            # Started under the lock so a concurrent request always observes
            # this job rather than an idle unit.
            process.start()

        logger.info(
            "Started ingestion job%s | course=%d lecture=%d unit=%d",
            ", superseding the previous one" if superseded is not None else "",
            *key,
        )
