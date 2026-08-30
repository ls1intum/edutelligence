# logos-agent — the agent runner

Runs coding agents in isolated containers, on serving capacity Logos is not
otherwise using, and gives that capacity back the moment a user needs it.

A session is one agent run: it gets a working copy, a task, and a Logos key.
It works unattended, and what it produces arrives as a draft pull request that
a human reviews like any other. Sessions can be told to deploy their result to
the **dev** environment and screenshot the pages they changed.

## Why this exists

Logos knows, at every moment, how much of its local serving fleet is in use.
Outside working hours that number is usually small, and the GPUs are idle
anyway. This service spends that idle capacity on the platform's own backlog —
and stops the moment the capacity is wanted for something else.

## How it is arranged

```
        browser ──► /api/agent/* ──► logos-agent ──► Docker Engine
                                          │              │
                                          │              └── session container ─┐
                                          │                   (no socket,       │
                                          │                    no root,         │
                                          ▼                    capped)          │
                                   logos-orchestrator ◄────────────────────────┘
                                    (models, load)          agent's model traffic
```

The runner holds the Docker socket. The sessions it creates do not: they get no
socket, no root, no capabilities, a read-only root filesystem, and memory, CPU,
and PID ceilings. That asymmetry is the isolation boundary, and it is set in
one place — `app/docker_engine.py:create_session_container`.

Agent model traffic goes to the orchestrator like any other caller's, with a
Logos key. It is authenticated, policy-checked, logged, and billed. Give that
key **LOW** priority so agent work can never outrank a user at the scheduler.

## Capacity, concretely

The runner reads `/logosdb/scheduler_state` every 15 seconds and computes one
number: the busy share of loaded serving slots.

| Condition | What happens |
|---|---|
| load < `START_BELOW_LOAD` (default 60 %) and no queue | queued sessions may start |
| load ≥ `PAUSE_ABOVE_LOAD` (default 85 %), **or** any user queueing | running sessions are paused |
| load falls back below `START_BELOW_LOAD` | paused sessions resume mid-task |
| orchestrator unreachable | nothing starts; anything running pauses |

Pausing freezes the process tree through the cgroup freezer, so a resumed
session picks up where it was rather than starting over. Yielding always takes
precedence over admitting: a pass that pauses does not also start something.

Two thresholds rather than one, because a single threshold makes sessions flap:
a session resumed at exactly the load that paused it pauses again next tick.

## Workspaces and parallelism

A **workspace** is one working copy on one Docker volume. **One session runs in
a workspace at a time** — two would write over each other. Parallelism comes
from having several workspaces; the ceiling across all of them is
`MAX_PARALLEL_SESSIONS`.

This is enforced twice: the admission query skips workspaces that are occupied,
and a partial unique index in the schema rejects a second active session for a
workspace outright. The second exists because a scheduler bug should raise
rather than corrupt a checkout.

## What is in the session image

Enough to work on any part of this repository, and nothing else:

| Tool | Version | Why |
|---|---|---|
| Claude Code | 2.1.245 | The agent. Driven headless: `claude -p … --output-format stream-json` |
| Node | 22 | logos-ui |
| Python | 3.11 (system) + **3.13 via uv** | Logos targets 3.13; bookworm ships 3.11, and a read-only rootfs cannot download an interpreter at runtime, so it is preinstalled into `/opt/uv-python` |
| Temurin JDK | 25 | logos-webservice targets Java 25. From Adoptium — Debian bookworm packages no JDK that new. `./mvnw` fetches Maven itself |
| gh | 2.98 | Opening the pull request |
| Chromium (Playwright) | 151 | Screenshots of the dev environment |

Versions are pinned as build args; bump them deliberately rather than letting a
session's behaviour drift between builds.

> **Adding a Dockerfile here?** The repository-root `.dockerignore` is a
> *whitelist*. Anything a Dockerfile copies must be listed there, or the build
> fails with `failed to compute cache key: … not found`.

## What a session may and may not do

**May:** read and change the working copy, run tests and linters, push a branch
under `agent/`, open a draft pull request, and — if enabled — have its result
deployed to dev and screenshotted.

**May not:** reach the Docker daemon, run as root, push to `main` or any
protected branch, dispatch a workflow, or touch production. The deploy is
dispatched *by this service*, with a token the container never receives, and
only for `logos_deploy-dev.yml`; any other workflow is refused in code.

Branch names are derived from the session id, not chosen by the agent, so two
sessions cannot collide and no workspace name can steer a push at a protected
branch.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `LOGOS_AGENT_API_KEY` | — | Logos key sessions call models with. **Required.** |
| `LOGOS_AGENT_DEFAULT_MODEL` | — | Model when a session does not name one |
| `LOGOS_AGENT_MAX_PARALLEL_SESSIONS` | `4` | Hard ceiling on concurrent sessions |
| `LOGOS_AGENT_START_BELOW_LOAD` | `0.60` | Start only below this load |
| `LOGOS_AGENT_PAUSE_ABOVE_LOAD` | `0.85` | Pause at or above this load |
| `LOGOS_AGENT_SESSION_MEMORY_MB` | `4096` | Per-session memory ceiling |
| `LOGOS_AGENT_SESSION_CPUS` | `2` | Per-session CPU ceiling |
| `LOGOS_AGENT_SESSION_TIMEOUT_S` | `10800` | Wall-clock ceiling per session |
| `LOGOS_AGENT_SESSION_GITHUB_TOKEN` | — | Given to containers; contents + PR write only |
| `LOGOS_AGENT_GITHUB_TOKEN` | — | Held here only; needs `workflow` scope for dev deploys |
| `LOGOS_AGENT_DEPLOY_ENABLED` | `false` | Whether dev deploys may be dispatched at all |
| `LOGOS_AGENT_REQUIRED_ROLE` | `logos_admin` | Realm role required to drive agents |

Two GitHub tokens on purpose. The container's can push and open pull requests;
it cannot dispatch a deploy even if the agent tries. The runner's can dispatch
the dev deploy; it never leaves this process.

## Running it

The service is behind a compose profile, so an existing deployment is unchanged
until you ask for it:

```bash
cd logos
COMPOSE_PROFILES=agent docker compose up -d logos-agent
```

Schema changes ship with the webservice's Liquibase changelog
(`019_agent_sessions.xml`), so the tables exist as soon as the webservice has
run its migrations.

The UI lives at **Agents** in the sidebar (`logos_admin` only): capacity, all
sessions, live transcripts, screenshots, and pull-request links.

### Local development

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -e '.[dev]'
LOGOS_AGENT_DEV_MODE=1 LOGOS_AGENT_AUTH_DISABLED=1 \
  uvicorn app.main:app --reload --port 8082
```

`LOGOS_AGENT_AUTH_DISABLED` without `LOGOS_AGENT_DEV_MODE` refuses to start —
an unauthenticated agent runner is not something to leave lying around.

```bash
pytest              # capacity gating, state machine, branch derivation
```

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/capacity` | Current load and whether a session may start |
| `GET`/`POST` | `/workspaces` | List and create workspaces |
| `DELETE` | `/workspaces/{id}` | Remove a workspace (refused while occupied) |
| `GET`/`POST` | `/sessions` | List and queue sessions |
| `GET` | `/sessions/{id}` | One session |
| `POST` | `/sessions/{id}/cancel` | Stop a session and remove its container |
| `GET` | `/sessions/{id}/events` | Transcript and status events after an id |
| `GET` | `/sessions/{id}/stream` | The same as server-sent events |
| `GET` | `/sessions/{id}/screenshots/{name}` | A captured page |

The UI polls `/events` rather than using `/stream`: `EventSource` cannot send
an `Authorization` header, and the token is what authorises the read.

## Operating notes

- **Restarts are safe.** On startup the runner reconciles: sessions whose
  containers are gone are settled, live containers are re-adopted, orphaned
  containers are removed.
- **A stuck session is capped**, not left to burn capacity — `SESSION_TIMEOUT_S`
  stops it and records the reason.
- **Nothing merges itself.** Pull requests are opened as drafts, and a person
  approves and merges exactly as they do for human work.
