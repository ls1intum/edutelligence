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

The session network carries the other half of it: an *internal* bridge, with
no route off the host, so the only thing an agent container can reach is the
model gateway. The runner verifies that rather than assuming it — a network
that already exists as a plain bridge stops the service instead of silently
giving every session external egress.

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

Freezing alone would not return the slot: the generation the agent already
started runs upstream, and a frozen client neither cancels it nor closes its
socket — it just stops reading, and the slot stays occupied for as long as the
pause lasts. So a paused session is also detached from the session network,
which ends the connection and lets the orchestrator release the slot. The
agent meets a network error when it resumes and retries, which is the
cheapest possible way to lose an in-flight answer. A session that cannot be
reattached stays paused rather than being thawed without a way to work.

Two thresholds rather than one, because a single threshold makes sessions flap:
a session resumed at exactly the load that paused it pauses again next tick.

## Workspaces and parallelism

A **workspace** is one working copy on one Docker volume. **One session runs in
a workspace at a time** — two would write over each other. Parallelism comes
from having several workspaces; the ceiling across all of them is
`MAX_PARALLEL_SESSIONS`.

Workspaces the runner creates for triggered work are named after it —
`issue-812-oom-on-startup`, `pr-772-add-an-agent-runner` — which is also what
appears in the branch (`logos/agent/issue-812-oom-on-startup/session-42`) and
in the workspace list. Once their work is finished their volume is reclaimed and the workspace is
retired — the row stays, because every finished session hangs off it, and
deleting it would take their history, the trigger references that keep
assigned work from being done twice, and any answer still waiting to be
delivered. An operator's own workspaces are never touched, and a retired one
is revived if the same issue comes back.

This is enforced twice: the admission query skips workspaces that are occupied,
and a partial unique index in the schema rejects a second active session for a
workspace outright. The second exists because a scheduler bug should raise
rather than corrupt a checkout.

Ten sessions is the default ceiling. The capacity thresholds decide how many
of them actually run at any moment.

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

> **Adding a file the gateway or the runner reads at runtime?** Put it in an
> image. A deployment copies exactly one file to its VM — the compose file —
> so a bind mount of anything else resolves to a path that does not exist
> there, and Docker creates an empty *directory* in its place rather than
> failing. That is how the gateway once came up with nginx's stock
> configuration and failed its health check forever.

## What a session may and may not do

**May:** read and change the working copy, run tests and linters, push a branch
under `logos/agent/`, open a draft pull request, and — if enabled — have its result
deployed to dev and screenshotted.

**May not:** reach the Docker daemon, run as root, push to `main` or any
protected branch, dispatch a workflow, or touch production. The deploy is
dispatched *by this service*, with a token the container never receives, and
only for `logos_deploy-dev.yml`; any other workflow is refused in code.

Branch names are derived from the session id, not chosen by the agent, so two
sessions cannot collide and no workspace name can steer a push at a protected
branch. The exception is a pull request handed to it, which keeps its own
branch — checked against the protected list all the same.

## Stopping it, and slowing it down

Two controls live in the database rather than in the environment, because
they are needed *during* something — an incident, a deploy, a surprise — and
editing an `.env` on a host to restart a service that is mid-session is not
what anybody wants to be doing then. Both are on the Agents page, both
survive a restart, and both are visible to whoever finds the runner stopped.

| Control | What it does |
|---|---|
| **Stop new sessions** (draining) | Nothing new starts. What is running finishes, and a paused session may still resume. |
| **Pause everything** | Running sessions are paused on the next pass and the capacity goes back to the platform. Nothing is cancelled: resuming picks the work up mid-task. |
| **Sessions at once** | A ceiling for now, overriding the configured one. Zero drains without pausing. |

## What gets worked on first

A session is admitted per capacity reading, so the order of the queue is what
the platform actually works on while it is busy. That order is urgency, not
arrival: a review (which holds a pull request shut) outranks a question,
which outranks new work, and the repository's own labels move it — a
`security fix` to the top, `documentation` down. `blocked`, `wontfix`,
`invalid`, `duplicate` and `stale` are not urgency but an answer: the runner
does not pick that work up at all, and says which label stopped it.

The mapping is in `app/priority.py`, in one table, for a repository that
labels things differently.

## Configuration

Two variables are required — a Logos key and a GitHub token. Everything else
has a default that is right for this deployment.

| Variable | Default | Meaning |
|---|---|---|
| `LOGOS_AGENT_API_KEY` | — | Logos key sessions call models with. **Required.** |
| `LOGOS_AGENT_GITHUB_TOKEN` | — | The agent account's token. **Required.** |
| `LOGOS_AGENT_GITHUB_LOGIN` | `LogosOSSAgent` | The account every token must belong to |
| `LOGOS_AGENT_DEFAULT_MODEL` | — | Model when a session does not name one. Optional: with exactly one local model reachable, that one is the default |
| `LOGOS_AGENT_TRIGGERS_ENABLED` | `true` | Kill switch for reacting to the repository |
| `LOGOS_AGENT_MAX_PARALLEL_SESSIONS` | `10` | Hard ceiling on concurrent sessions |
| `LOGOS_AGENT_START_BELOW_LOAD` | `0.60` | Start only below this load |
| `LOGOS_AGENT_PAUSE_ABOVE_LOAD` | `0.85` | Pause at or above this load |
| `LOGOS_AGENT_SESSION_MEMORY_MB` | `4096` | Per-session memory ceiling |
| `LOGOS_AGENT_SESSION_CPUS` | `2` | Per-session CPU ceiling |
| `LOGOS_AGENT_SESSION_TIMEOUT_S` | `10800` | Wall-clock ceiling per session (paused time does not count) |
| `LOGOS_AGENT_SESSION_MODEL_URL` | `http://logos-agent-gateway` | Where sessions send model traffic — a gateway that exposes only the orchestrator's `/v1` model surface, so a session never reaches the rest of the internal network |
| `LOGOS_AGENT_SESSION_GITHUB_TOKEN` | falls back to the token above | Given to containers; best without `workflow` scope |
| `LOGOS_AGENT_DEPLOY_ENABLED` | `false` | Whether dev deploys may be dispatched at all |
| `LOGOS_AGENT_REQUIRED_ROLE` | `logos_admin` | Realm role required to drive agents |

### The GitHub account

Everything this service does on GitHub happens as one account —
`LogosOSSAgent` by default. One identity whose commits, pull requests, and
comments are visibly the platform's own, whose access is withdrawn in one
place, and which owns nothing a human contributor owns.

A classic personal access token from that account needs exactly two scopes:

- **`repo`** — push branches, open pull requests, read commit status and checks.
- **`workflow`** — dispatch the dev deploy, and let a session change files
  under `.github/workflows/` like any other part of the repository.

Nothing else: no `admin:repo_hook` (the runner polls rather than listening for
webhooks, so it needs no inbound door), no package scopes, no organisation
administration. Outside the token, the account needs write access to the
repository, and — if the organisation enforces SAML — the token authorised
for it.

The account is not taken on trust. Both tokens are checked against it when
the service starts, and a token belonging to somebody else stops the service
rather than committing agent work under that person's name. The finalizer
checks again inside the container, immediately before it pushes.

**Two tokens if you can.** A second token of the same account *without*
`workflow` scope, given to session containers, means a session cannot dispatch
a deploy or edit a workflow file even if the agent tries — GitHub refuses such
a push outright.

With one token that scope is present, so the finalizer enforces the part that
matters itself: a session whose diff touches `.github/workflows/` fails
instead of pushing. A workflow file an agent wrote would otherwise run with
the repository's own secrets as soon as its pull request opened, and losing a
session's work is recoverable in a way that is not.

## Never a cloud model

Agent work is paid for in idle GPU time. A cloud deployment bills per token,
so a session must never reach one — not by naming a cloud model, not through
an alias of one, and not because the agent key was granted a cloud provider
by mistake.

The boundary is the platform's own key scoping: a Logos key reaches exactly
the deployments its permissions grant, and the gateway replaces whatever
credential a session sends with that key. **Give the agent key local
providers only.**

The runner refuses to assume that was done. It reads what the key can
actually reach and gates on the answer:

| What it reads | What happens |
|---|---|
| every reachable deployment is local | sessions run; those models are what the UI offers |
| any reachable deployment is a cloud provider | **no session starts at all**, and the reason names the models that would have cost money |
| the key does not resolve, or the database cannot be read | unknown — treated as unsafe |

It is re-established on every scheduler pass, not once at startup: permissions
are data, and a key can be granted a cloud provider at any time. A model that
is served both locally and in the cloud counts as cloud — the scheduler may
route to either.

## Working with it like a colleague

The agent has a GitHub account (`LogosOSSAgent`), and the point is that you
use it the way you use a person's:

| What you do | What it does |
|---|---|
| assign it an issue | works on it and opens a draft pull request |
| assign it a pull request | takes it over, on that pull request's own branch |
| request changes on one of its pull requests | addresses that review on its branch |
| comment on a pull request it is responsible for | reads the thread and answers (within a day of writing) |
| mention it anywhere by name | answers there (within a day); changes code only if that is what was asked |

No labels and no separate vocabulary — the ordinary gestures. **Consent is
per item:** nothing is picked up because it exists, only because somebody
assigned it, reviewed its work, or asked it something by name. That is why
this needs no service-wide opt-in to be safe; `LOGOS_AGENT_TRIGGERS_ENABLED`
exists as a kill switch, not as a second consent.

**Who may ask for what.** Anybody can comment on a public repository, and a
session that commits does so with the runner's credentials — so the ability
to direct a code change is checked against the repository's own collaborator
permissions. A question from outside is answered in words, with no branch;
a review from outside is left to a person. Assignment needs write access
anyway: GitHub only assigns collaborators.

Only a **changes-requested** review is work — an approval or a plain comment
is not, and an approval submitted after a change request withdraws it.
Comments are read from the last 24 hours: assignments and reviews are read
from the repository's current state, but comments are a stream, and without a
bound the first pass after a restart would read years of them.

**It says it heard you.** The moment a session is queued it reacts with 👀 on
what triggered it, so a question does not sit there looking ignored while the
platform waits for idle GPUs.

**It can answer.** The agent phase holds no GitHub credential, so it writes
its answer into its artefact directory and the runner posts it when the
session settles — in the thread the question was asked in, inline if it was
an inline question. The reply is produced by the untrusted phase; the posting
is done by the trusted one.

**Branches.** Work it starts itself goes on `logos/agent/…`. A pull request
handed to it keeps its own branch name, because renaming it would abandon the
pull request it belongs to. It never pushes to a fork (not ours to push) or
to a protected branch.

**Remembered forever.** Every reaction is recorded on the session as the
thing it reacted to — `issue-812`, `pr-772-assigned`,
`pr-772-review-5085681761`, `thread-772-3910035243`. A reference that already
has a session is never queued again, so an issue that stays assigned does not
produce a second pull request next week, and an answered question is not
answered twice. Only the *newest* changes-requested review of a pull request
counts as work; the older ones were answered by it. A session that failed is
re-queued by a person, who can see why it failed.

**Bounded.** At most half the parallel ceiling may be self-queued sessions,
so an operator queueing work by hand always finds room. Bots are ignored:
their findings reach the agent through the next review, not as a session per
note. Workspaces are created on demand up to the ceiling, since a session the
runner queued has nobody to prepare a working copy for it.

## Running it

The service is behind a compose profile, so an existing deployment is unchanged
until you ask for it:

```bash
cd logos
COMPOSE_PROFILES=agent docker compose up -d logos-agent
```

Schema changes ship with the webservice's Liquibase changelog
(`020_agent_sessions.xml`), so the tables exist as soon as the webservice has
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
| `GET` | `/models` | The locally served models a session may use |
| `GET` | `/triggers` | Whether the runner reacts to the repository, and what it queued |
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
- **Screenshots follow the deploy.** A session that asks for dev screenshots
  gets them only after the runner has dispatched its dev deploy and watched
  the environment serve again — the runner captures the pages in one-shot
  containers, so the photos show the revision the session just deployed, not
  the one that was live while the session ran.
