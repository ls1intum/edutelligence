"""Configuration for the agent runner.

Every knob is an environment variable so the service is configured the same way
as the rest of the stack (docker-compose passes them through). Defaults are the
values that are safe on a developer machine; production overrides them in
`.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    # --- database ---------------------------------------------------------
    db_host: str = os.getenv("DB_HOST", "logos-db")
    db_port: int = _int("DB_PORT", 5432)
    db_name: str = os.getenv("DB_NAME", "logosdb")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "root")

    # --- identity ---------------------------------------------------------
    keycloak_jwks_uri: str = os.getenv("KEYCLOAK_JWKS_URI", "")
    keycloak_issuer_uri: str = os.getenv("KEYCLOAK_ISSUER_URI", "")
    keycloak_audience: str = os.getenv("KEYCLOAK_AUDIENCE", "") or os.getenv("KEYCLOAK_CLIENT_ID", "logos")
    # Realm role that may drive agents. Sessions act on the dev environment and
    # can open pull requests, so this is deliberately the admin role.
    required_role: str = os.getenv("LOGOS_AGENT_REQUIRED_ROLE", "logos_admin")
    # Set to skip token verification. Only ever for local development; the
    # service refuses to start with this on unless LOGOS_AGENT_DEV_MODE is set.
    auth_disabled: bool = _bool("LOGOS_AGENT_AUTH_DISABLED", False)
    dev_mode: bool = _bool("LOGOS_AGENT_DEV_MODE", False)

    # --- the platform this runner serves ---------------------------------
    # This service (on the stack's internal network) reads capacity and
    # dispatches deploys from here.
    orchestrator_url: str = os.getenv("LOGOS_ORCHESTRATOR_URL", "http://logos-orchestrator:8080")
    # Where a *session container* sends its model traffic. Sessions live on
    # the session network, which must not reach the orchestrator itself (that
    # would hand a bypassPermissions agent the whole internal API), so they
    # are pointed at a gateway that forwards only the /v1 model surface.
    # The default is the compose service name of that gateway.
    session_model_url: str = os.getenv("LOGOS_AGENT_SESSION_MODEL_URL", "http://logos-agent-gateway")
    internal_secret: str = os.getenv("LOGOS_INTERNAL_SECRET", "")
    # The Logos key sessions authenticate with. It is what makes agent traffic
    # ordinary, accounted Logos traffic — give it LOW priority and a token
    # budget so agent work never outranks a user at the scheduler.
    agent_api_key: str = os.getenv("LOGOS_AGENT_API_KEY", "")
    default_model: str = os.getenv("LOGOS_AGENT_DEFAULT_MODEL", "")

    # --- container execution ---------------------------------------------
    docker_socket: str = os.getenv("LOGOS_AGENT_DOCKER_SOCKET", "/var/run/docker.sock")
    workspace_image: str = os.getenv(
        "LOGOS_AGENT_WORKSPACE_IMAGE",
        "ghcr.io/ls1intum/edutelligence/logos-agent-workspace:latest",
    )
    # The network sessions are attached to. It is created separately from the
    # stack's `internal` network so that egress rules can differ.
    session_network: str = os.getenv("LOGOS_AGENT_SESSION_NETWORK", "logos-agent-net")
    session_memory_mb: int = _int("LOGOS_AGENT_SESSION_MEMORY_MB", 4096)
    session_cpus: float = _float("LOGOS_AGENT_SESSION_CPUS", 2.0)
    session_pids_limit: int = _int("LOGOS_AGENT_SESSION_PIDS_LIMIT", 512)
    # The unprivileged user the session image runs as. The runner creates the
    # per-session artefact directory on the host as root, so it must hand it
    # over to this UID or the session cannot write its own output.
    session_uid: int = _int("LOGOS_AGENT_SESSION_UID", 10001)
    # Wall-clock ceiling for one session. A stuck agent burns capacity that the
    # whole point of this runner is to reclaim, so the cap is not optional.
    session_timeout_s: int = _int("LOGOS_AGENT_SESSION_TIMEOUT_S", 3 * 3600)

    # --- concurrency and capacity ----------------------------------------
    # Hard ceiling regardless of how idle the platform looks.
    max_parallel_sessions: int = _int("LOGOS_AGENT_MAX_PARALLEL_SESSIONS", 4)
    # A session may start only while the platform's busy share is below this.
    # Expressed as a fraction of reserved-to-total serving capacity.
    start_below_load: float = _float("LOGOS_AGENT_START_BELOW_LOAD", 0.60)
    # Above this, running sessions are paused so user traffic gets the GPUs
    # back. Must exceed start_below_load or sessions would flap.
    pause_above_load: float = _float("LOGOS_AGENT_PAUSE_ABOVE_LOAD", 0.85)
    scheduler_interval_s: float = _float("LOGOS_AGENT_SCHEDULER_INTERVAL_S", 15.0)

    # --- what a session may do -------------------------------------------
    repo_url: str = os.getenv("LOGOS_AGENT_REPO_URL", "https://github.com/ls1intum/edutelligence.git")
    repo_slug: str = os.getenv("LOGOS_AGENT_REPO_SLUG", "ls1intum/edutelligence")
    # Held by this service only. Needs `workflow` scope to dispatch the dev
    # deploy; it is never passed into a session container.
    github_token: str = os.getenv("LOGOS_AGENT_GITHUB_TOKEN", "")
    # Handed to session containers. Should be scoped to this repository with
    # contents and pull-request write only — no workflow scope, so a session
    # cannot dispatch a deploy even if it tries.
    session_github_token: str = os.getenv("LOGOS_AGENT_SESSION_GITHUB_TOKEN", "")
    # Deploys are triggered by this service, never from inside a session
    # container: the container never holds a token that can reach production.
    deploy_workflow: str = os.getenv("LOGOS_AGENT_DEPLOY_WORKFLOW", "logos_deploy-dev.yml")
    deploy_enabled: bool = _bool("LOGOS_AGENT_DEPLOY_ENABLED", False)
    # The only environment a session is ever allowed to affect.
    allowed_environment: str = os.getenv("LOGOS_AGENT_ALLOWED_ENVIRONMENT", "logos-dev")
    dev_base_url: str = os.getenv("LOGOS_AGENT_DEV_BASE_URL", "https://logos-dev.aet.cit.tum.de")

    # Branch names a session may push. Anything outside this prefix is refused
    # by the service before the container is even started.
    branch_prefix: str = os.getenv("LOGOS_AGENT_BRANCH_PREFIX", "agent/")
    protected_branches: tuple[str, ...] = field(
        default_factory=lambda: _csv("LOGOS_AGENT_PROTECTED_BRANCHES", ("main", "develop"))
    )

    # --- storage ----------------------------------------------------------
    # Where session artefacts (logs, screenshots) are kept, on a volume shared
    # with the session containers.
    artifact_root: str = os.getenv("LOGOS_AGENT_ARTIFACT_ROOT", "/var/lib/logos-agent/artifacts")
    artifact_volume: str = os.getenv("LOGOS_AGENT_ARTIFACT_VOLUME", "logos_agent_artifacts")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}" f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
