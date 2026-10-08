# logos-agent — the agent runner

Runs coding agents in isolated containers, on serving capacity Logos is not
otherwise using, and gives that capacity back the moment a user needs it.

A session is one agent run: it gets a working copy, a task, and a Logos key.
It works unattended, and what it produces arrives as a pull request that
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
number: the busy share of the serving slots **its own sessions would use**.

That filter matters. A fleet holds embedding models, rerankers and chat models
that share nothing but a building, and summing them answers a question nobody
asked — "6 of 120 slots busy" reads as an idle platform when all six of those
requests are on the one model the agent is served by, which is half its lane.
So the ratio counts the deployments the runner's key can reach — by provider
and model id, not by name, because the same model is served by providers this
key has no permission for and their idle slots would make a busy lane look
free. It falls back to the fleet-wide figure only when none of those
deployments is resident: there is nothing of ours to measure then, and the
older signal is the better of the two answers available. A key that reaches
*nothing* is a different question and is refused outright, so a paused
session is never resumed into a permission it no longer has. The **queue** is
deliberately not filtered — models share GPUs, so a person waiting on any of
them is a person this runner gets out of the way of.

**Minus its own share, where that is the right question.** The orchestrator
reports how busy a model is, and *who* is keeping it busy: how many of the
model's in-flight requests each caller key is making. A session may start
subagents, so one session can hold several of a model's slots at once —
every session's traffic, subagents included, goes through this runner's one
key, and the per-key figure for it is the runner's true share. That is what
comes off the figures. Against an orchestrator that does not report the
split, the runner falls back to an estimate: a running session has at most
one request outstanding, per model, and that many come off.

Whether to *hand capacity back* is a question about other people, so it is
decided on that adjusted figure. Without it a runner reads its own sessions
as user traffic — it pauses itself for them, the load it reacted to leaves
with them, it resumes, and it does it again — and its own sessions queueing
read as "users are queueing", the signal that means stop everything. A real
user waiting still shows, and still stops it.

Whether to *take more on* is a question about the model, and the estimate is
an upper bound: a running session may be between turns, running tests,
making no request at all. Subtracting too much there would add work to a
lane that is genuinely busy, so admission uses the figure as measured. What
bounds the runner's own concurrency is the parallel ceiling, not the load.

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

## Web search

Claude Code's own `WebSearch` works in sessions. It is a server-side tool:
Claude Code asks the API to run the searches, and the orchestrator does,
on DuckDuckGo (see "Web search" in `docs/context-windows.md`). The request
reaches it through the session gateway like any model call, so nothing is
installed or configured in the session.

Searches leave from the orchestrator, which honors the standard
`HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY` environment variables for a server or
CIT proxy, and result pages are never fetched. Queries are sent to
DuckDuckGo, so agents should avoid putting credentials or private repository
content in them. Search results are untrusted external data.

## What a session may and may not do

**May:** read and change the working copy, run tests and linters, push a branch
under `logos/agent/`, open a pull request, and — if enabled — have its result
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

## What the agent is told, and changing it

Every task carries two standing blocks: the **house rules** — the conventions
the agent works to — and the **environment notes**, which describe the
container it works in. Both ship as defaults in code and can be edited on the
page, taking effect on the next session rather than the next deployment.
They are prompts, and prompts are the part of an unattended agent most worth
adjusting after watching a few sessions: every line in the defaults is there
because a session went wrong without it.

Each session shows the exact text it was handed, so a surprising session can
be read rather than guessed at.

**It can run the repository's own hooks.** `pre-commit`'s hook environments
are installed into the session image at build time, where there is a network
to install them with — a session has none, and without this the instruction
to lint before finishing was one the agent could not follow. Sessions were
pushing unformatted code and learning nothing about it.

**And it finds out when its change turned the checks red.** A session ends
minutes before its pull request's checks conclude, so it never saw the one
verdict a person would notice immediately. The runner follows the checks of
what the session pushed, and a red one becomes another attempt with the
failure in its task.

## What gets worked on first

An operator can overrule it. The queue on the page carries three controls on
every session waiting in it — to the front, up one, down one — because the
order is what the runner works through while the platform is busy, and
which review is holding up a release is something the person watching knows
and the rules do not. A move past a session of equal priority goes one above
it: ties are broken by age, and nothing can make a session older.


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

Two things are required — a Logos key and a credential for the agent
account: either a GitHub token or a GitHub App (below). Everything else has
a default that is right for this deployment.

| Variable | Default | Meaning |
|---|---|---|
| `LOGOS_AGENT_API_KEY` | — | Logos key sessions call models with. **Required.** |
| `LOGOS_AGENT_GITHUB_TOKEN` | — | The agent account's token. **Required** unless the GitHub App fields are set (then ignored) |
| `LOGOS_AGENT_GITHUB_LOGIN` | `LogosOSSAgent` | The account every credential must belong to; with a GitHub App, that app's bot user |
| `LOGOS_AGENT_GITHUB_APP_ID` | — | The app's id. With the key below, replaces the personal tokens — the service mints short-lived installation tokens on demand |
| `LOGOS_AGENT_GITHUB_APP_PRIVATE_KEY` | — | The app's private key: the PEM, or its base64 for a one-line value |
| `LOGOS_AGENT_GITHUB_INSTALLATION_ID` | resolved from the repository | The app's installation on this repository |
| `LOGOS_AGENT_GITHUB_TOKEN_TTL_S` | `1800` | How long a minted token may live, in seconds; GitHub caps it at `3600`, and the token is re-minted before it lapses |
| `LOGOS_AGENT_DEFAULT_MODEL` | — | Model when a session does not name one. Optional: with exactly one local model reachable, that one is the default |
| `LOGOS_AGENT_TRIGGERS_ENABLED` | `true` | Kill switch for reacting to the repository |
| `LOGOS_AGENT_ANALYSIS_NIGHTLY_HOUR_UTC` | `0` | UTC hour of the nightly re-analysis of linked team repositories whose branch head moved; `-1` turns it off |
| `LOGOS_AGENT_MAX_PARALLEL_SESSIONS` | `10` | Hard ceiling on concurrent sessions |
| `LOGOS_AGENT_START_BELOW_LOAD` | `0.60` | Start only below this load |
| `LOGOS_AGENT_PAUSE_ABOVE_LOAD` | `0.85` | Pause at or above this load |
| `LOGOS_AGENT_SESSION_MEMORY_MB` | `4096` | Per-session memory ceiling |
| `LOGOS_AGENT_SESSION_CPUS` | `2` | Per-session CPU ceiling |
| `LOGOS_AGENT_SESSION_TIMEOUT_S` | `0` | Wall-clock ceiling per session; `0` is none, which is the default |
| `LOGOS_AGENT_SESSION_MODEL_URL` | `http://logos-agent-gateway` | Where sessions send model traffic — a gateway that exposes only the orchestrator's `/v1` model surface, so a session never reaches the rest of the internal network |
| `LOGOS_AGENT_SESSION_GITHUB_TOKEN` | falls back to the token above | Given to containers; best without `workflow` scope; ignored when the GitHub App fields are set |
| `LOGOS_AGENT_DEPLOY_ENABLED` | `false` | Whether dev deploys may be dispatched at all |
| `LOGOS_AGENT_REQUIRED_ROLE` | `logos_admin` | Realm role required to drive agents |

### The GitHub account

Everything this service does on GitHub happens as one account —
`LogosOSSAgent` by default. One identity whose commits, pull requests, and
comments are visibly the platform's own, whose access is withdrawn in one
place, and which owns nothing a human contributor owns.

**A GitHub App, if you can.** A token of the account is a standing door: it
stays usable until somebody revokes it, and a log line, transcript, or
environment dump that names it publishes it for that whole span. A GitHub
App is the other way to hold the same access. The service keeps only the
app's *signing key*, which cannot act on its own, and mints an installation
token on demand — a bearer credential that lives at most an hour and is
re-minted automatically before the previous one lapses. What reaches a
container is a minted token, so a credential that is published by accident
stops being one within its own lifetime.

Run it: create the app, give it these repository permissions — Contents,
Pull requests, and Issues *read and write*; Checks *read*; Actions *read
and write* — the runner dispatches the dev deploy and reads its runs, and
no other permission grants those; Workflows *read and write*; Metadata
*read* — plus Organisation members *read* if the deployment uses
`LOGOS_AGENT_TRUSTED_TEAMS`, install it on the repository, and set
`LOGOS_AGENT_GITHUB_APP_ID` and `LOGOS_AGENT_GITHUB_APP_PRIVATE_KEY` (the
installation id is optional — the service resolves it from the repository
at the first mint). Set `LOGOS_AGENT_GITHUB_LOGIN` to the app's bot user,
for example `LogosOSSAgent[bot]`; while the app is configured the personal
tokens are ignored.

One difference from the two-token setup: one kind of token then serves every
phase, and it carries the app's full permissions, including dispatching a
deploy. The scope boundary a second token without `workflow` used to give is
gone, so the finalizer enforces the part that matters itself — the same
enforcement the one-token setup relies on.

Personal access tokens work too, for a deployment that does not run the
account as an app. A classic personal access token from that account needs
exactly two scopes:

- **`repo`** — push branches, open pull requests, read commit status and checks.
- **`workflow`** — dispatch the dev deploy, and let a session change files
  under `.github/workflows/` like any other part of the repository.

Nothing else: no `admin:repo_hook` (the runner polls rather than listening for
webhooks, so it needs no inbound door), no package scopes, no organisation
administration. Outside the token, the account needs write access to the
repository, and — if the organisation enforces SAML — the token authorised
for it.

The account is not taken on trust. Every credential is checked against it
when the service starts, and one belonging to somebody else stops the service
rather than committing agent work under that person's name. With personal
access tokens that is `GET /user`. With a GitHub App the check asks the App
for its bot user and the minted installation token which App it belongs to —
installation tokens cannot answer `/user` — and the finalizer re-checks the
token against the App id inside the container, immediately before it pushes.

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
| assign it an issue | works on it and opens a pull request |
| assign it a pull request | takes it over, on that pull request's own branch |
| request changes on one of its pull requests | addresses that review on its branch |
| add it as a reviewer | reviews the diff, and fixes what it found if the branch is ours |
| comment on a pull request it is responsible for | reads the thread and answers (within a day of writing) |
| mention it anywhere by name | answers there (within a day); changes code only if that is what was asked |

**Whose word counts.** A session pushes branches and answers in this
repository's name, so what may direct it is a question about people:
membership of the `logos-developers` or `logos-maintainers` team
(`LOGOS_AGENT_TRUSTED_TEAMS`). Where the runner cannot ask — a token without
`read:org` — it falls back to the coarser rule of write permission on the
repository. Comments from anybody else are left out of the task and the
omission is disclosed, the reporter's own included: anybody can open an
issue on a public repository, and a maintainer can repeat what matters in
their own words.

The review apps this repository runs on its own pull requests
(`LOGOS_AGENT_REVIEW_BOTS`, `coderabbitai[bot]` and `Claudia-Anthropica`
by default) are readable and, on a pull request this runner already owns,
may also direct: a `CHANGES_REQUESTED` or `@mention` from one of them is
the ordinary next step after the agent opened the work. What they wrote
also travels with a task somebody trusted has already directed, because a
handover that dropped the review left the agent reconstructing one from
the diff. Strangers still cannot start a session or steer a push. Setting
the variable to nothing removes the exception.

**It asks Claudia to review what it opened.** A fresh pull request from an
issue session requests `Claudia-Anthropica` (`LOGOS_AGENT_PR_REVIEWERS`)
in addition to whatever CODEOWNERS already names. A reused pull request
asks again — GitHub treats a repeat as a no-op when she is already
requested. Empty the variable to leave only CODEOWNERS.

**Team review requests count too.** Asking `logos-maintainers` or
`logos-developers` (`LOGOS_AGENT_REVIEW_TEAMS`) is treated like asking the
agent by name: GitHub never puts the bot login in `requested_reviewers` for
a team request, so without this list the gesture was silent.

**A requested review is a review, not a commit.** Being added as a
reviewer — by name or through a team — never gets the agent the branch:
the session reads `refs/pull/<n>/head`, may not push, and its findings land
as one review whose inline comments (`review-comments.json`) sit on the
lines they are about, with `reply.md` as the summary. A line GitHub cannot
place turns the remarks into one ordinary comment instead. A change on a
pull request the agent does not own is asked for in a comment by somebody
whose word counts (see below).

**It reads the pull request it is asked about.** A question on somebody
else's pull request used to be answered from a checkout of the default
branch — the agent was asked about a diff it had never seen, and could only
say so. It now starts from that pull request's own code
(`refs/pull/<n>/head`, which exists for forks too). Whether it may *change*
anything is a separate question with a plain answer: it gets the branch when
somebody who may direct this runner asked, and the head is in this
repository and not protected. A fork's branch and a protected one are never
pushed to, whoever asks; there the answer is words.

**It does not take over its own work.** This repository assigns every pull
request to its author, so one the agent opens comes back a moment later as
one assigned to it. Reviews and questions on it still reach the agent; a
handover of what it has just written does not.

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
Comments are read from where the last complete pass stopped — a mark kept in
the database, so a question asked while the runner was paused is still found
when it comes back. Assignments and reviews are read from the repository's
current state and need no window; comments are a stream, so a fresh
deployment starts with the last 24 hours and no pass ever reaches back
further than a week.

**It says where your request is.** Three reactions, on the comment you
wrote:

| | |
|---|---|
| 👀 | accepted and in the queue |
| 🚀 | being worked on right now |
| 😕 | it did not work out — the session failed |

👀 is posted *after* the session row exists, so it is never a promise of work
that is not queued; and because the row is what the queue is, a restart
changes nothing about it. GitHub's reaction palette is fixed and has no
hourglass, so these three are the states it can show.

**An issue is its thread, not its body.** A title, an empty body and the
whole report in the first comment is an ordinary way to file one, and a
session handed the title alone can only say so — which is exactly what
happened on an issue whose description was a maintainer's comment. The
comments travel with the task now — the ones from the trusted teams
(`LOGOS_AGENT_TRUSTED_TEAMS`, `logos-developers` and `logos-maintainers` by
default). Everybody else is left out and counted, the person who opened the
issue included: anybody can open one, and the session that reads it will
push a branch. Where the teams cannot be read at all — a token without
`read:org` — the coarser rule stands in for them: whoever may write to the
repository.

**It can see what you attached.** An issue whose whole description is a
screenshot is unreadable to a sandbox with no network — the agent met one of
those with `WebFetch`, was refused, read code for an hour and changed
nothing. The runner has the token and the egress the session deliberately
does not, so it fetches the images a request refers to into the session's
artefact directory and tells the agent where they are. Bounded: five images,
eight megabytes each, and only what arrives as an image.

**It always says something back.** Every triggered session answers on the
thread it came from — including a session that changed nothing, which is the
outcome most easily mistaken for being ignored. The agent writes that answer
itself; when it writes none, the runner posts what it knows instead (what
was attempted, what came of it, where the transcript is), because silence on
a thread somebody is waiting on is the one thing a colleague never does.

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

**Bounded.** Self-queued sessions may *run* up to the parallel ceiling less a
fifth of it, at least one place, kept for people — triggered sessions carry
higher priorities and would otherwise win every slot. Keeping half the fleet
idle for a session nobody has asked for is the wrong trade on a platform
whose point is spending what would go to waste. What does not fit runs
later: it is queued, in priority order, and visible as work waiting rather
than left in the repository where nobody sees it. Bots are ignored:
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
- **A deploy does not interrupt the work.** Session containers are not part of
  the compose stack — the runner starts them through the Docker socket — so
  they survive a redeploy of the runner and are picked up again by the
  reconciliation above. What a deploy *does* replace alongside the runner is
  the model gateway, and a session talking to a gateway being restarted under
  it loses the turn it is in the middle of. So shutdown freezes what is
  running first: the same pause the capacity logic uses, which detaches the
  container from the session network and ends the upstream generation
  cleanly. The rows stay `paused`, the new runner adopts them, and the
  scheduler resumes them mid-task. `stop_grace_period` is 30 s for this, and
  whatever cannot be frozen in time simply runs through the deploy as it did
  before.
- **A session ends when it is done, not when a clock says so.** There is no
  wall-clock limit unless a deployment sets one. A clock is the wrong
  instrument: a session that has read the repository for two hours and is
  halfway through a change is not stuck, and stopping it throws away
  everything it has done — uncommitted, in a checkout the next session
  resets. One went that way: ninety minutes and thirty-eight million tokens,
  killed at the deadline with nothing to show. What this runner protects is
  capacity, and capacity is protected by the things that measure it — the
  pause, the parallel ceiling, the trigger quota — none of which care how
  long a session has been at it. A session that really is stuck is visible
  on the page and can be cancelled there.
- **Yielding does not cost the work.** Freezing a session and cutting it off
  the model network — which is how capacity is handed back — ends the answer
  it was reading, and the agent meets a dead connection when it thaws. That
  used to end the session: every session that was paused failed with `exit
  code 1`, and every session that was never paused finished. The agent
  phase now recognises the interruption and continues the same conversation
  in the same checkout, up to three times, so a pause costs a retry instead
  of an afternoon.
- **A pull request is one piece of work, not one session per round.** An
  issue becomes a change, a review comes back, then another — and each round
  used to meet the repository as a stranger: the whole checkout read again,
  the reasoning behind the change gone, millions of tokens for a change of
  ten lines. A session that continues what its workspace was doing (the same
  branch) keeps the conversation instead. The working copy stays put, the
  workspace follows the branch its session pushed, and a workspace whose pull
  request is still open is never swept — so the same checkout and the same
  conversation carry the change from assignment to merge.

  Only the conversation is carried. The agent's home is still wiped between
  sessions: `settings.json` hooks, `core.hooksPath`, a global `CLAUDE.md`,
  shell profiles and build caches are executable configuration written by a
  session that held a push token, and the next session must not inherit
  them. Transcripts are data the same agent already authored.
- **A request the runner could not finish comes back by itself.** A trigger
  reference counts as handled the moment a session exists for it — that is
  what keeps an assignment from producing a pull request a week — so a
  failed session used to take its request with it, permanently invisible to
  every later pass. A failure now takes the work up again with the reason
  attached, bounded by the same three attempts as everything else, so a task
  that cannot be done stops rather than loops.
- **Work can be run again.** A failed session keeps its task, its workspace,
  its branch and the thread it came from, and *Run again* queues all of it as
  a new session. This is the only way back for work the runner took on
  itself: a trigger counts as handled the moment a session exists for it, so
  no later pass finds that issue, review or question again.
- **Nothing merges itself.** A person
  approves and merges exactly as they do for human work.
- **Screenshots follow the deploy.** A session that asks for dev screenshots
  gets them only after the runner has dispatched its dev deploy and watched
  the environment serve again — the runner captures the pages in one-shot
  containers, so the photos show the revision the session just deployed, not
  the one that was live while the session ran.
