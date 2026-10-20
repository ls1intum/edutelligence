# Logos: LLM Engineering made easy

**Logos** is an LLM Engineering Platform that includes usage logging, billing, central resource management, policy-based model selection, scheduling, and monitoring.

## Architecture documentation

The published documentation — user, administrator, and developer guides, the
subsystem and terminology reference, and per-role UI guides — lives at
<https://ls1intum.github.io/edutelligence/logos/> (source: `logos/docs/`,
built with Docusaurus by the `Build Logos Documentation` workflow).

See the [request lifecycle reference](logos-orchestrator/src/logos/pipeline/README.md) for the classification, scheduling, context-resolution, LogosNode/HTTP forwarding, and completion boundaries.

See the [agent runner](logos-agent/README.md) for how Logos runs coding agents in isolated containers on its own spare serving capacity, and the boundaries those sessions work within.

## Nightly model benchmarks

Automatic calibration runs first (05:00–08:00 Europe/Berlin by default).
Benchmarks use the remaining time. Only one calibration or benchmark runs
across the cluster, including manual starts.

Logos admins can add model/worker pairs to a persistent nightly rotation from
**Model Details → Performance**. Both activation and deactivation require
confirmation. Schedules start disabled.

- Test at most **2 enabled pairs per night**, one worker at a time. Untested
  pairs come first, then the oldest previous attempt. Unavailable pairs are skipped.
- Start configurations between **05:00 and 07:50 Europe/Berlin**. At 08:00,
  continue only if at least 50% of measured requests completed successfully.
- Stop after **5 minutes without output or completed requests**. Retry a stalled
  configuration once before 07:50, then skip it if it stalls again.
- Compare the current settings with selected batching-parameter variants on a
  fixed dataset. Show the model and planned values above the dataset previews.
- Restore the original worker configuration after the plan. Store results for
  review; do not automatically apply a winning configuration to production.

See the [nightly benchmark guide](docs/admin/nightly-benchmarks.md)
for activation, selection, limits, deployment, recovery and API details. The
[manual benchmark guide](logos-orchestrator/docs/benchmark-configuration.md)
describes the separate dataset editor and benchmark batches.

# Setup

## Prerequisites

- **Python 3.13**
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- **Docker** for containerization
- You need to request [Artemis Developer Access](https://request.aet.cit.tum.de/) to be able to push your changes to the edutelligence repo.

## Installation

### uv

Install uv, if you haven't already:

```bash
pip install uv
```

#### Dependencies

From the repository root (`edutelligence/`), install the orchestrator dependencies:

```bash
cd logos/logos-orchestrator
uv sync --locked --python 3.13
```

For later dependency syncs, run `uv sync --locked` in `logos/logos-orchestrator/`.
The parent `logos/pyproject.toml` only configures formatting; it is not the
orchestrator package. The warning about its missing `[project]` table is harmless.

In PyCharm, use `logos/logos-orchestrator/.venv/bin/python` as the interpreter.
The **Package requirements are not satisfied** notification means that this
interpreter is missing dependencies or has different versions than the project
requires. **Sync project** installs them using uv. No separate `requirements.txt` is needed.

## Development

### PR Naming Convention

Prefix all PRs with `` `Logos`: `` followed by a short description. The `L` in `Logos` must be capitalised.

Example: `` `Logos`: Add team management endpoints ``

### Pre-commit hooks

Logos ships with a [pre-commit](https://pre-commit.com/) config that runs the
formatters and linters consistent with our CI gate (`.github/workflows/logos_lint.yml`):

| Hook | Purpose |
|------|---------|
| `pre-commit-hooks` | YAML/TOML syntax, large files, merge conflicts, EOF, trailing whitespace |
| `autoflake` | Removes unused imports and variables |
| `isort` | Sorts imports (`profile=black`, 120 cols) |
| `black` | Formats Python (`line-length = 120`, `target = py313`) |
| `flake8` | Lints against `logos/.flake8` (E203/W503 disabled for black compatibility) |

The hook config is scoped to `^logos/` so it only ever touches files in this
service, even when invoked from the repo root.

**One-time setup** (per clone):

```bash
# Install pre-commit (macOS via brew, or pip in any env)
brew install pre-commit          # or:  pip install pre-commit

# Install the git hook so `git commit` runs the checks automatically.
# Run from the repo root, not from logos/, so the parent .pre-commit-config.yaml
# (which delegates to logos/ via sub-pre-commit) is picked up.
cd ..    # to edutelligence/
pre-commit install
```

**Manual runs:**

```bash
# Run all hooks against every file in logos/ (matches what CI runs):
pre-commit run --config logos/.pre-commit-config.yaml --all-files

# Run a single hook (useful when iterating):
pre-commit run --config logos/.pre-commit-config.yaml black --all-files
pre-commit run --config logos/.pre-commit-config.yaml flake8 --all-files

# Run on just the files you've staged (what the git hook does on commit):
pre-commit run --config logos/.pre-commit-config.yaml
```

> [!IMPORTANT]
> The lint CI job fails when any hook reports a change or a violation, so run
> pre-commit before pushing — `pre-commit install` automates this. If you need
> to land a one-off commit without the hook, prefer fixing the issue over
> bypassing; `--no-verify` is only for genuine emergencies and the CI gate
> will still fail.

## Docker Compose Files

| File | Purpose |
|------|---------|
| `docker-compose.yaml` | **Production** — pulls pre-built images from Harbor |
| `docker-compose.dev.yaml` | **Development** — builds images locally from source |

## Running the Service (Development)
To deploy Logos locally:

1. Clone the repository:

   ```bash
   git clone https://github.com/ls1intum/edutelligence/
   ```

2. Build and Run Logos Docker Container

   From the `logos/` directory:

   ```bash
   docker compose -f docker-compose.dev.yaml up --build
   ```

    From the `logos/logos-ui/` directory:

   ```bash
   cd logos-ui/
   ng serve
   ```

   > 💡 **Note for Linux users:** Should you encounter `EACCES` permissions errors during the setup, consult the [Official npm Documentation](https://docs.npmjs.com/resolving-eacces-permissions-errors-when-installing-packages-globally).
3. Log In

   Once running, open the UI at:
   ```
   http://localhost:4200/
   ```
   and click **Sign in**. You'll be redirected to the local Keycloak instance
   (seeded from `keycloak/tum-realm.json`) to log in. A handful of dev accounts
   are seeded there, all with the password `password`:

   | Username              | Role         |
   |-----------------------|--------------|
   | tobias.wasner         | logos_admin  |
   | alexandra.szuminska   | app_admin    |
   | henriette.huhn        | app_developer|
   | blub.fisch            | app_developer|
   | fridoline.fuchs       | app_developer|
   | pech.vogel            | app_developer (no roles at all — useful for testing the no-team / no-access screens) |

   A fresh dev stack starts with no teams, so `app_developer` accounts won't
   have access to anything yet. Three ways to fix that:

   - **Manually** (default): log in as `tobias.wasner` (or another
     `app_admin`/`logos_admin`), create a team under **Teams**, and add the
     developer account(s) you want to test as members — they'll pick up
     access the next time they log in.
   - **From a Keycloak group**: as `tobias.wasner` (a `logos_admin`), create a
     team under **Teams** and set its **Keycloak group** — in the create dialog
     or later on the team's **Settings** tab. Everyone carrying that group or
     realm role joins the team on their next login and leaves it again once
     they no longer carry it. The seeded realm offers `logos-dev` and
     `maiss-dev` for this.
   - **Automatically**: set `KEYCLOAK_AUTO_PROVISION_TEAMS=true` for the
     `logos-webservice` service in `docker-compose.dev.yaml`. On their next
     login, any account whose Keycloak roles include a team role (one ending
     in `-dev`, `-team`, or `-group` — see `KEYCLOAK_TEAM_ROLE_SUFFIXES`) gets
     that team created and joined automatically. The seeded realm already
     carries these on most dev accounts: `logos-dev` → team **"Logos"**,
     `maiss-dev` → team **"Maiss"** (the derived name strips the suffix and
     title-cases what's left, so the umlaut doesn't survive).

   To add more dev accounts, edit `keycloak/tum-realm.json` and restart the
   `keycloak` container.

4. Explore the API

   A full overview of available endpoints can be found at: https://logos.aet.cit.tum.de/docs

## Scheduling & Capacity Management

Logos includes an independently toggleable subsystem for proactive worker management:

| Subsystem | Env Variable | Default | What it does |
|-----------|-------------|---------|-------------|
| **Capacity Planner** | `LOGOS_CAPACITY_PLANNER_ENABLED` | `true` | Background loop (30s cycles) that sleeps idle lanes, wakes lanes on demand, and tunes vLLM GPU memory utilization. |

Set to `false` to disable. Add to the `environment` section of `logos-orchestrator` in `docker-compose.yaml`:
```yaml
environment:
  LOGOS_CAPACITY_PLANNER_ENABLED: "true"
```

Worker nodes auto-calibrate model VRAM profiles (how much GPU memory each model needs when loaded vs sleeping). Logos stores the profiles in its database — the workers keep none on disk — and sends them to each worker at startup. No extra configuration needed on the worker side.

## Connecting via SSH

Once your access is granted and VPN is active:

```bash
ssh <yourtumkuerzel>@logos-test.aet.cit.tum.de
```

The Logos instance lives at `/opt/logos` on the server.

## Accessing the API and the Admin UI

Everything is served on the default HTTPS port (443): the Admin UI, the Swagger docs, and the completion API. Traefik routes by path — API paths (`/v1`, `/openai`, `/jobs`, `/api`, `/docs`, …) win, everything else serves the UI. Port `8080` remains a TLS alias for the completion API for existing clients.

Open the Admin UI at:

```
https://logos-test.aet.cit.tum.de/
```

Explore the API via Swagger (a `GET /v1` returns 404 by design — use `/docs`):

```
https://logos-test.aet.cit.tum.de/docs
```

### Audio transcription and translation

Logos implements the OpenAI-compatible multipart audio APIs:

- `POST /v1/audio/transcriptions` transcribes audio in its original language.
- `POST /v1/audio/translations` transcribes and translates audio into English.

The selected model must be available to the caller's Logos API key. Both cloud
providers (including deployment-scoped Azure OpenAI Whisper endpoints) and
compatible Logos worker-node backends receive the original multipart fields and
file metadata. JSON, verbose JSON, plain text, SRT, and VTT responses are
relayed with the upstream status and content type.

```bash
curl https://logos-test.aet.cit.tum.de/v1/audio/transcriptions \
  -H "Authorization: Bearer $LOGOS_API_KEY" \
  -F "file=@./speech.wav" \
  -F "model=whisper-1" \
  -F "response_format=verbose_json" \
  -F "timestamp_granularities[]=word"
```

Audio file contents and credentials are excluded from Logos usage logs and
durable async-job records; only filename, media type, and size metadata are
recorded. A request accepts one audio file, defaulting to the upstream Whisper
limit of 25 MiB. Set `LOGOS_MAX_AUDIO_UPLOAD_BYTES` to configure the file limit
for another compatible backend. Text form fields default to 64 KiB each and can
be configured with `LOGOS_MAX_AUDIO_FORM_FIELD_BYTES`. Logos also enforces a
30 MiB total multipart request limit before Starlette spools the file; configure
that independently with `LOGOS_MAX_AUDIO_REQUEST_BYTES`.

When the provider reports duration-based usage, Logos stores millisecond
precision and applies the provider's per-second catalogue price. This avoids
discarding fractional audio duration while retaining the integer usage schema.

### Decision models

`POST /v1/systemone` answers typed questions about a text (yes/no, choice,
score) with calibrated probabilities. The endpoint uses the schema of TypeSafe's
Jev API. Logos serves it with decision models such as `autotrust/JEV-27B-VL` on
a plain vLLM lane. Requests for other models go to the model's lane, where
vLLM answers them itself. See [Decision models](docs/decision-models.md) for the
API and for the worker-node configuration.

### Batch processing

Logos serves the OpenAI Batch API (`/v1/files` for the input and result files,
`/v1/batches` for the job lifecycle) for workloads with many requests and
nobody waiting.

A batch runs in one of two places, decided when its input file is uploaded:

- **At the provider**, when one the key may use has a Batch API that serves
  every model the file names. That is where the provider's batch rate applies
  (about half the standard price), so it is preferred.
- **In Logos**, otherwise — a model served by a worker node has no upstream
  Batch API, and a cloud model can be missing from its provider's batch
  offering. Logos then schedules the file's requests itself at the lowest queue
  priority: they fill whatever capacity interactive traffic leaves and finish as
  fast as that allows. No discount (the requests are ordinary requests), but the
  same API.

Both paths answer the same routes, so a script can upload, poll every few
minutes, and chain the next batch onto the last without knowing which one it
got; `logos_execution` on the batch object says which it was. Send
`X-Logos-Batch-Execution: logos` or `provider` to force one.

Whatever a batch names in its request lines is checked against the key's model
permissions line by line, the ids it hands back are owned by the key's team (a
lifecycle call for another team's id is a 404), and its usage is booked into the
same budget and statistics as everything else — at the provider's batch rate
where one is configured. See
[docs/batch-processing.md](docs/batch-processing.md) for the full route list,
Azure's batch availability, and the limits.

The **Batches** page in the UI does the same thing without a script: upload a
`.jsonl`, watch the progress, download the results.

For a single latency-tolerant request the async job API remains simpler:
`POST /jobs/v1/chat/completions` returns `202` with a `Location` header, and
`GET /jobs/{job_id}` polls for the result.

## Accessing the Database

The PostgreSQL database is not directly reachable from outside the server. You need to tunnel through SSH, which most database clients (e.g. DBeaver) support natively.

### DBeaver SSH Tunnel Configuration

In DBeaver, create a new PostgreSQL connection and configure the **SSH** tab as follows:

| Field | Value |
|-------|-------|
| Host/IP | `logos-test.aet.cit.tum.de` |
| Port | `22` |
| User Name | your TUM username (e.g. `ge69yun`) |
| Authentication | Public Key |
| Private Key | path to your SSH private key (e.g. `~/.ssh/id_ed25519`) |

Then on the **Main** tab:

| Field | Value |
|-------|-------|
| Host | `localhost` |
| Port | `5432` |
| Database | `logosdb` |
| Username | `postgres` |
| Password | `root` |

### Manual SSH Tunnel

If you prefer a manual tunnel instead of using a GUI client:

```bash
ssh -L 5433:127.0.0.1:5432 <yourtumkuerzel>@logos-test.aet.cit.tum.de
```

Then connect your database client to `localhost:5433` with the credentials above.

# License and Attribution
For license attribution and upstream provenance of the LiteLLM model catalog data, see [litellm-model-catalog.NOTICE](logos-webservice/src/main/resources/litellm-model-catalog.NOTICE).
