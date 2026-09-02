"""Request and response models, and the session state machine.

The state machine is small enough to state in one place, and every transition
the service performs goes through :func:`can_transition` so an illegal one
fails loudly instead of leaving a row in a state the UI cannot render.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SessionStatus(StrEnum):
    QUEUED = "queued"  # accepted, waiting for capacity
    STARTING = "starting"  # container being created
    RUNNING = "running"  # agent working
    PAUSED = "paused"  # container stopped to give capacity back
    FINALIZING = "finalizing"  # agent exited, the trusted finalizer is pushing
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({SessionStatus.SUCCEEDED, SessionStatus.FAILED, SessionStatus.CANCELLED})
ACTIVE_STATUSES = frozenset(
    {
        SessionStatus.QUEUED,
        SessionStatus.STARTING,
        SessionStatus.RUNNING,
        SessionStatus.PAUSED,
        # Finalizing still occupies the workspace: the finalizer container
        # has the volume mounted and runs git in the working copy.
        SessionStatus.FINALIZING,
    }
)

# Transitions the service is allowed to make. Paused sessions return to
# running (their container is unpaused), never to starting: the container and
# its workspace survive the pause, so re-running setup would lose work.
_ALLOWED: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.QUEUED: frozenset({SessionStatus.STARTING, SessionStatus.CANCELLED, SessionStatus.FAILED}),
    SessionStatus.STARTING: frozenset({SessionStatus.RUNNING, SessionStatus.FAILED, SessionStatus.CANCELLED}),
    SessionStatus.RUNNING: frozenset(
        {
            SessionStatus.PAUSED,
            SessionStatus.FINALIZING,
            SessionStatus.SUCCEEDED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }
    ),
    SessionStatus.PAUSED: frozenset({SessionStatus.RUNNING, SessionStatus.CANCELLED, SessionStatus.FAILED}),
    # Finalizing is not pausable and never returns to running: the agent
    # container is gone, so a pause would have nothing to freeze, and a
    # resume would hand the row back with no supervisor to finish it. The
    # finalizer runs to completion, or the session is cancelled or failed.
    SessionStatus.FINALIZING: frozenset({SessionStatus.SUCCEEDED, SessionStatus.FAILED, SessionStatus.CANCELLED}),
    SessionStatus.SUCCEEDED: frozenset(),
    SessionStatus.FAILED: frozenset(),
    SessionStatus.CANCELLED: frozenset(),
}


def can_transition(current: SessionStatus, target: SessionStatus) -> bool:
    return target in _ALLOWED[current]


class EventKind(StrEnum):
    LOG = "log"
    STATUS = "status"
    PULL_REQUEST = "pull_request"
    DEPLOY = "deploy"
    SCREENSHOT = "screenshot"
    CAPACITY = "capacity"
    ERROR = "error"


# --- workspaces -----------------------------------------------------------


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_branch: str = Field(default="main", max_length=128)

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        # The name becomes part of a Docker volume and a git branch, so keep it
        # to characters that are safe in both.
        cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in v.strip().lower())
        if not cleaned.strip("-_"):
            raise ValueError("name must contain at least one alphanumeric character")
        return cleaned


class Workspace(BaseModel):
    id: int
    name: str
    base_branch: str
    volume_name: str
    created_by: str
    created_at: datetime
    active_sessions: int = 0


# --- sessions -------------------------------------------------------------


class SessionCreate(BaseModel):
    workspace_id: int
    task: str = Field(min_length=8, max_length=8000)
    # Which Logos-served model drives the agent. Absent means the runner picks
    # the configured default.
    model: str | None = Field(default=None, max_length=200)
    # Open a pull request when the work finishes and the diff is non-empty.
    open_pull_request: bool = True
    # Deploy the resulting build to the dev environment after the PR is opened.
    # Refused unless the service is configured with deploy_enabled.
    deploy_to_dev: bool = False
    # URLs (paths on the dev environment) to screenshot once deployed.
    screenshot_paths: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("screenshot_paths")
    @classmethod
    def _relative_paths(cls, v: list[str]) -> list[str]:
        for path in v:
            if not path.startswith("/") or path.startswith("//"):
                raise ValueError(f"screenshot path must be an absolute path on the dev host: {path}")
        return v


class SessionSummary(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str
    task: str
    status: SessionStatus
    model: str | None
    branch_name: str | None
    pr_url: str | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    error: str | None
    tokens_in: int
    tokens_out: int
    cost_eur: float
    screenshot_count: int = 0


class SessionEvent(BaseModel):
    id: int
    session_id: int
    ts: datetime
    kind: EventKind
    payload: dict


class CapacityState(BaseModel):
    """What the runner currently believes about spare serving capacity."""

    load: float  # 0..1, reserved share of local serving slots
    total_slots: int
    busy_slots: int
    sessions_running: int
    sessions_queued: int
    sessions_paused: int
    max_parallel: int
    may_start: bool
    reason: str
