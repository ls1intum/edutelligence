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


# The file a session writes an answer into, relative to its artefact
# directory. Shared contract: the task text tells the agent to write it, the
# runner reads it and posts what it finds. It lives here rather than in
# either of those modules so neither has to import the other.
REPLY_FILE = "reply.md"
# The one line the agent writes about what it changed. The runner commits
# with it, because the agent is the only one that knows what the change is —
# and because a commit subject derived from the task reads like the task.
COMMIT_FILE = "commit.txt"


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
    # The Logos Keycloak client. Client roles are read only from this client
    # in the token — the same scoping the webservice applies
    # (logos.auth.client-id) — never from other clients in the realm.
    keycloak_client_id: str = os.getenv("KEYCLOAK_CLIENT_ID", "logos")
    # The internal role name that may drive agents. Sessions act on the dev
    # environment and can open pull requests, so this is deliberately the
    # admin role. Tokens carry the deployment's *external* role name, which
    # is mapped onto this one by `keycloak_roles_logos_admin`.
    required_role: str = os.getenv("LOGOS_AGENT_REQUIRED_ROLE", "logos_admin")
    # The external Keycloak role name(s) that grant `required_role`. The
    # browser JWT carries the name the deployment configured for its
    # administrators (itg-admin by default), not the internal value — so the
    # check maps first, exactly like the webservice does
    # (logos.auth.roles.logos-admin / KeycloakRoleMapper). Same environment
    # variable name, so one .env configures both services.
    keycloak_roles_logos_admin: tuple[str, ...] = field(
        default_factory=lambda: _csv("KEYCLOAK_ROLES_LOGOS_ADMIN", ("itg-admin",))
    )
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
    # are pointed at a gateway that forwards only the /v1 model surface and
    # injects the model credential — the container sends none of its own.
    # The default is the compose service name of that gateway.
    session_model_url: str = os.getenv("LOGOS_AGENT_SESSION_MODEL_URL", "http://logos-agent-gateway")
    internal_secret: str = os.getenv("LOGOS_INTERNAL_SECRET", "")
    # The Logos key: the runner authenticates its capacity reads with it, and
    # the session gateway injects it into the agent's model calls. It is what
    # makes agent traffic ordinary, accounted Logos traffic — give it LOW
    # priority and a token budget so agent work never outranks a user at the
    # scheduler. It no longer enters a session container at all.
    agent_api_key: str = os.getenv("LOGOS_AGENT_API_KEY", "")
    # Which model drives a session that does not name one. Optional: when it
    # is unset and the key reaches exactly one locally served model, that one
    # is the default — a single-model deployment then needs no model
    # configuration at all. With several reachable, the session names one
    # (the UI lists them) or the runner says which are available.
    default_model: str = os.getenv("LOGOS_AGENT_DEFAULT_MODEL", "")

    # --- container execution ---------------------------------------------
    docker_socket: str = os.getenv("LOGOS_AGENT_DOCKER_SOCKET", "/var/run/docker.sock")
    workspace_image: str = os.getenv(
        "LOGOS_AGENT_WORKSPACE_IMAGE",
        "ghcr.io/ls1intum/edutelligence/logos-agent-workspace:latest",
    )
    # The network the untrusted agent phase is attached to. It is an
    # *internal* bridge: no external egress at all, so the only reachable
    # peer is the credential-injecting model gateway on the same network.
    session_network: str = os.getenv("LOGOS_AGENT_SESSION_NETWORK", "logos-agent-net")
    # The network the trusted helper containers run on — checkout
    # preparation, post-agent commit/push, screenshots. Unlike the session
    # network it may reach the outside (GitHub, the dev environment); the
    # agent itself never runs there.
    session_egress_network: str = os.getenv("LOGOS_AGENT_SESSION_EGRESS_NETWORK", "logos-agent-egress-net")
    session_memory_mb: int = _int("LOGOS_AGENT_SESSION_MEMORY_MB", 4096)
    session_cpus: float = _float("LOGOS_AGENT_SESSION_CPUS", 2.0)
    session_pids_limit: int = _int("LOGOS_AGENT_SESSION_PIDS_LIMIT", 512)
    # The unprivileged user the session image runs as. The runner creates the
    # per-session artefact directory on the host as root, so it must hand it
    # over to this UID or the session cannot write its own output.
    session_uid: int = _int("LOGOS_AGENT_SESSION_UID", 10001)
    # Whose word the agent acts on. A session pushes branches and answers on
    # behalf of this repository, so what may direct it is a decision about
    # people, not about permissions that happen to be attached to a fork or
    # a triage role. Named teams in the repository's own organisation; the
    # runner falls back to "may write to this repository" when it cannot ask
    # (a token without `read:org`), which is the older, coarser rule.
    trusted_teams: tuple[str, ...] = tuple(
        team.strip()
        for team in os.getenv("LOGOS_AGENT_TRUSTED_TEAMS", "logos-developers,logos-maintainers").split(",")
        if team.strip()
    )
    # Wall-clock ceiling for one session, or 0 for none — which is the
    # default. A clock is the wrong thing to stop an agent with: a session
    # that has read the repository for two hours and is halfway through a
    # change is not stuck, and killing it throws away everything it has done
    # without committing any of it. What this runner actually protects is
    # capacity, and that is protected by the things that measure capacity —
    # the pause, the parallel ceiling, the trigger quota — none of which
    # care how long a session has been at it. A session that really is stuck
    # is a thing a person can see on the page and cancel.
    session_timeout_s: int = _int("LOGOS_AGENT_SESSION_TIMEOUT_S", 0)
    # One helper container (checkout preparation, finalization) must not
    # outlive the session budget either: these are git and GitHub
    # round-trips, not agent work, and a stuck helper would pin its session
    # in 'starting' forever.
    helper_timeout_s: int = _int("LOGOS_AGENT_HELPER_TIMEOUT_S", 600)

    # --- concurrency and capacity ----------------------------------------
    # Hard ceiling regardless of how idle the platform looks. Ten is what the
    # platform is expected to carry when it is otherwise idle; the capacity
    # thresholds below decide how many of them actually run at any moment,
    # and each still needs a free workspace of its own.
    max_parallel_sessions: int = _int("LOGOS_AGENT_MAX_PARALLEL_SESSIONS", 10)
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
    # The GitHub account every token here must belong to. Agent work is
    # supposed to be recognisable and revocable as one identity: one account
    # whose pushes, pull requests, and comments are visibly the platform's
    # own, whose access can be withdrawn in one place, and which owns nothing
    # a human contributor owns. Both tokens are checked against it at
    # startup, and the finalizer checks again inside the container before it
    # pushes — a token belonging to a person would otherwise commit agent
    # work under that person's name.
    github_login: str = os.getenv("LOGOS_AGENT_GITHUB_LOGIN", "LogosOSSAgent")
    # Held by this service only. Needs `workflow` scope to dispatch the dev
    # deploy; it is never passed into a session container.
    github_token: str = os.getenv("LOGOS_AGENT_GITHUB_TOKEN", "")
    # Handed to session containers. Best issued as a second token of the same
    # account without `workflow` scope, so a session cannot dispatch a deploy
    # or edit a workflow file even if it tries. Falling back to the runner's
    # token keeps a one-token deployment working — the runner says so at
    # startup, because that fallback gives up the scope boundary between the
    # two phases.
    session_github_token: str = os.getenv("LOGOS_AGENT_SESSION_GITHUB_TOKEN", "") or os.getenv(
        "LOGOS_AGENT_GITHUB_TOKEN", ""
    )
    # Deploys are triggered by this service, never from inside a session
    # container: the container never holds a token that can reach production.
    deploy_workflow: str = os.getenv("LOGOS_AGENT_DEPLOY_WORKFLOW", "logos_deploy-dev.yml")
    # Builds and publishes the service images. It runs on pull requests (and
    # main/release) but never on plain branch pushes, and PR builds publish
    # pr-<number> tags, never latest — so a deploy of a session branch must
    # wait for this workflow's run and use the PR tag it published.
    build_workflow: str = os.getenv("LOGOS_AGENT_BUILD_WORKFLOW", "logos_build-and-push-docker.yml")
    deploy_enabled: bool = _bool("LOGOS_AGENT_DEPLOY_ENABLED", False)
    # The only environment a session is ever allowed to affect.
    allowed_environment: str = os.getenv("LOGOS_AGENT_ALLOWED_ENVIRONMENT", "logos-dev")
    dev_base_url: str = os.getenv("LOGOS_AGENT_DEV_BASE_URL", "https://logos-dev.aet.cit.tum.de")

    # The prefix of branches this runner *creates*. Everything in this
    # repository lives under `logos/`, and agent work is a subtree of that,
    # so a glance at a branch name says both what it belongs to and who made
    # it. A branch the runner did not create — a pull request handed to it by
    # a person — keeps its own name: renaming it would abandon the pull
    # request it belongs to.
    branch_prefix: str = os.getenv("LOGOS_AGENT_BRANCH_PREFIX", "logos/agent/")
    protected_branches: tuple[str, ...] = field(
        default_factory=lambda: _csv("LOGOS_AGENT_PROTECTED_BRANCHES", ("main", "develop"))
    )

    # --- reacting to the repository --------------------------------------
    # Whether the runner queues sessions of its own when something happens on
    # GitHub. On by default: starting this service at all is already the
    # deliberate decision (it lives behind a compose profile), and the real
    # consent is per item — an issue or pull request only becomes agent work
    # by carrying the label or being assigned to the agent account. A second,
    # invisible switch on top of those would only be a way to have the
    # feature deployed and quietly not working. It remains configurable as a
    # kill switch: turning it off stops the automation without taking the
    # runner and its UI down with it.
    #
    # Everything else about the feature — poll interval, how far back a
    # restarted runner looks, how many self-queued sessions may be active —
    # is a constant in `triggers.py`, derived where it depends on anything.
    triggers_enabled: bool = _bool("LOGOS_AGENT_TRIGGERS_ENABLED", True)

    # --- storage ----------------------------------------------------------
    # Where session artefacts (logs, screenshots) are kept, on a volume shared
    # with the session containers.
    artifact_root: str = os.getenv("LOGOS_AGENT_ARTIFACT_ROOT", "/var/lib/logos-agent/artifacts")
    artifact_volume: str = os.getenv("LOGOS_AGENT_ARTIFACT_VOLUME", "logos_agent_artifacts")

    @property
    def session_token_is_runner_token(self) -> bool:
        """Whether session containers hold the runner's own token.

        True when no separate session token was configured. The token then
        carries `workflow` scope, so the scope boundary between the agent
        phase and the runner is gone and the finalizer enforces the part
        that matters — CI files — by itself.
        """
        return bool(self.session_github_token) and self.session_github_token == self.github_token

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}" f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
