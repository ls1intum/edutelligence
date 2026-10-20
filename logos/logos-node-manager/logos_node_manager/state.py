"""Deployment records on disk.

One JSON file per deployment under ``<state dir>/deployments``. The command line creates the file. From then on only
the daemon writes it. Every write replaces the file atomically, so a reader sees the old or the new record and never a
half-written one.

The record is also the memory of the manager: after a restart it continues from the recorded phase.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from logos_node_manager.errors import StateError

logger = logging.getLogger(__name__)

# A deployment id becomes a file name, so it is restricted to characters that are safe there.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# The Docker tag grammar, and the same limit the deploy workflow checks before it writes the tag to the .env file.
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")

MAX_EVENTS = 60
KEEP_FINISHED = 30

# The local name ``<image>:previous`` keeps the image of the version that ran before. A deployment cannot ask for this
# tag: the manager moves the name to the running image before it swaps, so the requested release would be lost.
PREVIOUS_TAG = "previous"


class Phase(str, Enum):
    QUEUED = "queued"
    PULLING = "pulling"
    # Reserved: waiting for the running requests of the node to finish. This version passes through it.
    DRAINING = "draining"
    SWAPPING = "swapping"
    VERIFYING = "verifying"
    ROLLING_BACK = "rolling_back"
    DONE = "done"


class Outcome(str, Enum):
    SUCCEEDED = "succeeded"
    # Compose had nothing to recreate: the container already ran the requested image.
    UNCHANGED = "unchanged"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class FailureKind(str, Enum):
    PULL_FAILED = "pull_failed"
    SWAP_FAILED = "swap_failed"
    VERIFY_FAILED = "verify_failed"
    ROLLBACK_FAILED = "rollback_failed"
    INTERNAL_ERROR = "internal_error"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def validate_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError(f"invalid deployment id {value!r}: use 1 to 64 letters, digits, '.', '_' or '-'")
    return value


def validate_tag(value: str) -> str:
    if not _TAG.fullmatch(value):
        raise ValueError(f"invalid image tag {value!r}")
    if value == PREVIOUS_TAG:
        raise ValueError(f"the image tag {value!r} is reserved for the previous version")
    return value


@dataclass
class Deployment:
    """One request to replace the worker container, and everything the manager learned while it ran."""

    id: str
    tag: str
    requested_at: str
    requested_by: str = ""
    phase: Phase = Phase.QUEUED
    outcome: Outcome | None = None
    failure: FailureKind | None = None
    message: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    # Unexpected errors of the manager itself since the phase began. After a few, the deployer gives up on the phase.
    attempts: int = 0

    # The container and image that ran before the deployment. None on a host without a worker container.
    previous_container_id: str | None = None
    previous_running: bool | None = None
    previous_image_id: str | None = None
    previous_image_ref: str | None = None
    # The image that the "previous" name pointed to until this deployment moved it to the image above. It is removed
    # when the deployment has ended.
    stale_image_id: str | None = None

    target_image_ref: str | None = None
    target_image_id: str | None = None
    new_container_id: str | None = None

    # The end of the failed container's log, taken before the rollback removes that container.
    failure_logs: str = ""
    events: list[dict[str, str]] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.phase is Phase.DONE

    def to_dict(self) -> dict:
        data = {name: getattr(self, name) for name in self.__dataclass_fields__}
        data["phase"] = self.phase.value
        data["outcome"] = self.outcome.value if self.outcome else None
        data["failure"] = self.failure.value if self.failure else None
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Deployment":
        known = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        try:
            known["phase"] = Phase(known.get("phase", Phase.QUEUED.value))
            known["outcome"] = Outcome(known["outcome"]) if known.get("outcome") else None
            known["failure"] = FailureKind(known["failure"]) if known.get("failure") else None
            return cls(**known)
        except (ValueError, TypeError) as exc:
            raise StateError(f"invalid deployment record: {exc}") from exc


def _write_atomically(path: Path, payload: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def _create_exclusively(path: Path, payload: str) -> bool:
    """Create ``path`` with ``payload`` unless it exists. True if this call created it.

    The content is written to a temporary file first and linked into place, so a reader never sees a partial file. A
    file system without hard links gets the plain exclusive create instead, where a reader may see a partial file for
    a moment. The reader treats that as "not ready yet".
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError:
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                return False
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            return True
        return True
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


class StateStore:
    """The deployment records and the heartbeat file of one manager."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.deployments_dir = state_dir / "deployments"
        self.heartbeat_file = state_dir / "heartbeat"
        # Names of files that were skipped, so that the daemon reports each one once and not on every pass.
        self._ignored: set[str] = set()

    def ensure(self) -> None:
        self.deployments_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, deployment_id: str) -> Path:
        return self.deployments_dir / f"{validate_id(deployment_id)}.json"

    @staticmethod
    def _dump(deployment: Deployment) -> str:
        return json.dumps(deployment.to_dict(), indent=2, sort_keys=True) + "\n"

    def submit(self, deployment: Deployment) -> Deployment:
        """Queue a deployment. A second request with the same id returns the first one, so a retry attaches to it."""
        self.ensure()
        validate_tag(deployment.tag)
        if _create_exclusively(self._path(deployment.id), self._dump(deployment)):
            return deployment
        existing = self.load(deployment.id)
        if existing is None:
            # The file exists but is not readable yet: another submit is writing it.
            time.sleep(0.2)
            existing = self.load(deployment.id)
        if existing is None:
            raise StateError(f"deployment {deployment.id} exists but cannot be read")
        if existing.tag != deployment.tag:
            raise StateError(f"deployment id {deployment.id} is already used for tag {existing.tag}")
        return existing

    def load(self, deployment_id: str) -> Deployment | None:
        """The record, or None if there is none or it is not readable yet."""
        path = self._path(deployment_id)
        try:
            return Deployment.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, StateError) as exc:
            logger.warning("Deployment record %s is not readable: %s", path.name, exc)
            return None

    def save(self, deployment: Deployment) -> None:
        self.ensure()
        _write_atomically(self._path(deployment.id), self._dump(deployment))

    def all(self) -> list[Deployment]:
        """Every readable record, oldest request first. A file whose name is not a deployment id is not a record."""
        if not self.deployments_dir.is_dir():
            return []
        records = []
        for path in self.deployments_dir.glob("*.json"):
            if not _ID.fullmatch(path.stem):
                if path.name not in self._ignored:
                    self._ignored.add(path.name)
                    logger.warning("Ignoring %s: its name is not a deployment id", path)
                continue
            record = self.load(path.stem)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda record: (record.requested_at, record.id))

    def next_unfinished(self) -> Deployment | None:
        return next((record for record in self.all() if not record.finished), None)

    def latest(self) -> Deployment | None:
        records = self.all()
        return records[-1] if records else None

    def prune(self, keep: int = KEEP_FINISHED) -> None:
        """Delete the oldest finished records beyond ``keep``."""
        finished = [record for record in self.all() if record.finished]
        for record in finished[: max(0, len(finished) - keep)]:
            with contextlib.suppress(FileNotFoundError):
                self._path(record.id).unlink()

    # ------------------------------------------------------------------ Heartbeat

    def touch_heartbeat(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _write_atomically(self.heartbeat_file, utc_now() + "\n")

    def heartbeat_age(self) -> float | None:
        """Seconds since the daemon last signalled that it is alive, or None if it never did."""
        try:
            return max(0.0, time.time() - self.heartbeat_file.stat().st_mtime)
        except FileNotFoundError:
            return None
