"""Sequencing of per-lecture-unit ingestion jobs.

A second ingestion request for a lecture unit that is already being processed
used to be dropped. Artemis has by then switched to the new run's token, so the
old job reported against a token nobody listened to and the new run never sent
a single status update.

The newest request wins. It is started at once but must claim the unit's slot
before doing any work, and the job it replaced holds that slot until its thread
exits. Cancellation is cooperative and can be late; a thread ending is not. So
a slow-dying job can never finish after its successor and overwrite fresh
content with stale content.

Nothing here interrupts a job on a timer: a superseded job always stops at a
checkpoint of its own, never mid-write. The one bound is on the *waiting* side.
A job wedged with no reachable checkpoint would otherwise block its lecture
unit forever — every later request would queue behind it and Artemis would keep
re-dispatching into the same wait. Past ``_MAX_JOIN_SECONDS`` the successor
proceeds anyway; the wedged job keeps its cancel flag set and so still cannot
write. It should never fire, and logs an error when it does.

A queued run sends nothing while it waits, and does not need to: Artemis treats
a run as stuck only after 20 minutes without a callback, well beyond this wait.
"""

import threading
from threading import Event, Thread
from typing import Dict, Tuple

from iris.common.cancellation import CancellationSignal
from iris.common.logging_config import get_logger

logger = get_logger(__name__)

JobKey = Tuple[int, int, int]

# How long to wait for a superseded job before starting its successor anyway.
# This never interrupts the superseded job — it only limits how long the new one
# stays patient, and the old one still stops only at a checkpoint.
#
# Lower bound: it must exceed Weaviate's insert timeout (90s), so that any write
# the old job had already begun has landed or failed before the new one may
# start. Every write site checks the cancel flag immediately beforehand, so the
# old job cannot begin another one.
# Upper bound: it must stay below Artemis's 20-minute stuck detection
# (``LectureContentProcessingScheduler.NO_CALLBACK_TIMEOUT_MINUTES``), or a
# queued run gets re-dispatched while it is still waiting.
_MAX_JOIN_SECONDS = 180.0


class IngestionJobHandler:
    """Runs one ingestion job per lecture unit, newest request winning."""

    def __init__(
        self,
        max_join_seconds: float = _MAX_JOIN_SECONDS,
    ):
        self._lock = threading.Lock()
        self._latest: Dict[JobKey, Event] = {}  # cancel event of newest request
        self._slot: Dict[JobKey, Thread] = {}  # thread currently allowed to work
        self._max_join_seconds = max_join_seconds

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

    def await_turn(
        self,
        course_id: int,
        lecture_id: int,
        lecture_unit_id: int,
        cancel_event: Event,
    ) -> bool:
        """Block until this job may work on the unit.

        Called by the job's own thread before it touches anything. Waits for
        whichever job holds the unit to exit, then claims the slot.

        Args:
            cancel_event: This job's own event; set if it is superseded while
                queued, in which case there is nothing left for it to do.

        Returns:
            True if the slot is now held, False if this job was superseded
            while waiting and should exit without running.
        """
        key = (course_id, lecture_id, lecture_unit_id)
        me = threading.current_thread()

        while True:
            with self._lock:
                holder = self._slot.get(key)
                if holder is None or holder is me or not holder.is_alive():
                    self._slot[key] = me
                    return True

            # join() is itself the notification: it returns the instant the
            # holder's thread ends. The timeout is not a wait, only the point
            # at which a job that never reaches a checkpoint stops blocking us.
            holder.join(timeout=self._max_join_seconds)

            if cancel_event.is_set():
                logger.info(
                    "Queued ingestion job superseded before it started | "
                    "course=%d lecture=%d unit=%d",
                    *key,
                )
                return False

            if holder.is_alive():
                logger.error(
                    "Superseded ingestion job still alive after %.0fs; starting "
                    "anyway | course=%d lecture=%d unit=%d",
                    self._max_join_seconds,
                    *key,
                )
                with self._lock:
                    self._slot[key] = me
                return True
