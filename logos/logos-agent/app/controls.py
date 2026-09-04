"""What an operator can change about the runner while it is running.

The environment configures a deployment. This configures a moment: stopping
the automation and lowering the parallel ceiling are things somebody needs
*during* something, from the page they are already looking at — not by
editing an `.env` on a host and restarting a service that is in the middle of
ten sessions.

The kill switch has two halves, because "stop" means two different things
depending on what is wrong:

* **draining** — start nothing new. What is already running runs to the end,
  and a paused session may still resume. This is what you want when the
  agent's *work* is fine but you need the fleet to go quiet, or before a
  deploy.
* **paused** — hand everything back now. Running sessions are paused on the
  next pass and nothing resumes until the switch is released. Paused, not
  cancelled: the work survives and picks up mid-task.

Alongside it, a ceiling for now, overriding the configured one.

All of it is persisted, because a runner that forgets it was stopped is not
stopped, and read through a short-lived cache so the scheduler can consult it
on every decision without a query each time.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace

from . import db
from .config import settings

logger = logging.getLogger(__name__)

# How long a reading is reused. Short enough that pressing the switch takes
# effect on the next pass, long enough that the scheduler does not query per
# decision.
_CACHE_S = 2.0

RUNNING = "running"
DRAINING = "draining"
PAUSED = "paused"
MODES = (RUNNING, DRAINING, PAUSED)


@dataclass(frozen=True)
class Controls:
    """The runtime state of the operator controls."""

    mode: str = RUNNING
    mode_reason: str = ""
    # None means "whatever the environment configured".
    max_parallel_override: int | None = None
    updated_by: str = ""

    @property
    def paused(self) -> bool:
        """Whether running sessions must be handed back to the platform."""
        return self.mode == PAUSED

    @property
    def max_parallel(self) -> int:
        return settings.max_parallel_sessions if self.max_parallel_override is None else self.max_parallel_override

    @property
    def _reason_suffix(self) -> str:
        return f" ({self.mode_reason})" if self.mode_reason else ""

    def admission_block(self) -> str:
        """Why nothing new may start right now, or an empty string."""
        if self.mode == PAUSED:
            return f"the runner is paused{self._reason_suffix}"
        if self.mode == DRAINING:
            return f"the runner is draining: no new sessions{self._reason_suffix}"
        if self.max_parallel <= 0:
            return "the parallel ceiling is set to zero"
        return ""

    def may_resume(self) -> bool:
        """Whether a paused session may be resumed at all.

        Draining does not hold work back that is already under way — that is
        the difference between it and a pause.
        """
        return self.mode != PAUSED


DEFAULT = Controls()

# What the runner assumes before it has ever managed to read its controls:
# nothing may start, and nothing resumes. A process restarted during a
# database outage must not decide that the persisted `paused` it cannot see
# means `running` — the whole point of persisting the switch is that a
# restart does not release it.
UNREAD = Controls(mode=PAUSED, mode_reason="the runner has not read its controls yet")

_cached: Controls = UNREAD
_read_at: float = 0.0
_ever_read: bool = False


def cached() -> Controls:
    """The last reading, without touching the database."""
    return _cached


async def current() -> Controls:
    """The controls as they are now, from a cache of a couple of seconds.

    A database that cannot be read leaves the previous reading in place: the
    controls are an operator's intent, and forgetting a pause because of a
    transient error would be the wrong way to fail.
    """
    global _cached, _read_at, _ever_read
    now = time.monotonic()
    if _ever_read and now - _read_at < _CACHE_S:
        return _cached
    try:
        row = await db.get_controls()
    except Exception as exc:
        # Keep whatever was last known — which, before the first successful
        # read, is the state that blocks everything.
        logger.warning("could not read the runner controls; keeping the previous reading: %s", exc)
        return _cached
    _read_at = now
    _ever_read = True
    if row is None:
        _cached = DEFAULT
        return _cached
    override = row.get("max_parallel")
    mode = str(row.get("mode") or RUNNING)
    fresh = Controls(
        mode=mode if mode in MODES else RUNNING,
        mode_reason=str(row.get("mode_reason") or ""),
        max_parallel_override=int(override) if override is not None else None,
        updated_by=str(row.get("updated_by") or ""),
    )
    if fresh != _cached:
        logger.info(
            "runner controls: %s, max parallel=%s%s",
            fresh.mode,
            fresh.max_parallel,
            f" (set by {fresh.updated_by})" if fresh.updated_by else "",
        )
    _cached = fresh
    return _cached


async def set_mode(*, mode: str, reason: str, by: str) -> Controls:
    """Run, drain, or pause."""
    if mode not in MODES:
        raise ValueError(f"unknown mode '{mode}' (expected one of {', '.join(MODES)})")
    await db.set_controls(mode=mode, mode_reason=reason if mode != RUNNING else "", updated_by=by)
    return await _refresh()


async def set_max_parallel(*, limit: int | None, by: str) -> Controls:
    """Set or clear the runtime ceiling on concurrent sessions."""
    await db.set_controls(max_parallel=limit, clear_max_parallel=limit is None, updated_by=by)
    return await _refresh()


async def _refresh() -> Controls:
    global _read_at
    _read_at = 0.0
    return await current()


def forget() -> None:
    """Drop the cache, back to the state that has read nothing."""
    global _cached, _read_at, _ever_read
    _cached, _read_at, _ever_read = UNREAD, 0.0, False


__all__ = [
    "DRAINING",
    "UNREAD",
    "MODES",
    "PAUSED",
    "RUNNING",
    "Controls",
    "DEFAULT",
    "cached",
    "current",
    "forget",
    "replace",
    "set_max_parallel",
    "set_mode",
]
