# Logos: LLM Engineering made easy

**Logos** is an LLM Engineering Platform that includes usage logging, billing, central resource management, policy-based model selection, scheduling, and monitoring.

## Architecture documentation

See the [request lifecycle reference](logos-orchestrator/src/logos/pipeline/README.md) for the classification, scheduling, context-resolution, LogosNode/HTTP forwarding, and completion boundaries.

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

Create a virtual environment and install the dependencies:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install .
```

If that does not work, try pinning to Python 3.13 explicitly:

```bash
uv venv .venv --python 3.13
source .venv/bin/activate
uv pip install .
```

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
   have access to anything yet. Two ways to fix that:

   - **Manually** (default): log in as `tobias.wasner` (or another
     `app_admin`/`logos_admin`), create a team under **Teams**, and add the
     developer account(s) you want to test as members — they'll pick up
     access the next time they log in.
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

Worker nodes auto-calibrate model VRAM profiles (how much GPU memory each model needs when loaded vs sleeping). Profiles persist in the worker's state directory and are sent to Logos over the existing websocket heartbeat. No extra configuration needed on the worker side.

## Scheduler Benchmarking

To evaluate scheduler behaviour against the running Logos API, replay a scripted workload via the `/v1` endpoint using the helper in `tests/support/scheduling/run_api_workload.py`.

A short guide on crafting compatible workload CSVs lives next to the sample workload in `tests/fixtures/scheduling/README.md`.

### Testing Classification vs Direct Model Selection

Logos supports two operational modes that can be benchmarked:

**1. Direct Model Selection (Scheduling Only)**

Test scheduling behavior with a specific model. Classification is skipped.

```bash
docker compose exec logos-orchestrator \
  python logos/tests/support/scheduling/run_api_workload.py \
    --logos-key "YourLogosApiKey" \
    --workload logos/tests/fixtures/scheduling/sample_workload_direct.csv \
    --api-base http://localhost:8080 \
    --latency-slo-ms 10000 \
    --output logos/tests/results/scheduling/api_benchmark_direct.csv
```

**2. Classification Mode (Classification + Scheduling)**

Test the full classification pipeline. Logos selects the best model based on prompt content.

```bash
docker compose exec logos-orchestrator \
  python logos/tests/support/scheduling/run_api_workload.py \
    --logos-key "YourLogosApiKey" \
    --workload logos/tests/fixtures/scheduling/sample_workload_classify.csv \
    --api-base http://localhost:8080 \
    --latency-slo-ms 10000 \
    --output logos/tests/results/scheduling/api_benchmark_classify.csv
```

**3. Mixed Mode (Both in One Workload)**

Test both modes together to compare behavior side-by-side.

```bash
docker compose exec logos-orchestrator \
  python logos/tests/support/scheduling/run_api_workload.py \
    --logos-key "YourLogosApiKey" \
    --workload logos/tests/fixtures/scheduling/sample_workload_mixed.csv \
    --api-base http://localhost:8080 \
    --latency-slo-ms 10000 \
    --output logos/tests/results/scheduling/api_benchmark_mixed.csv
```

### Workload CSV Format

Workload files include the following columns:
- **`request_id`** - Unique identifier for each request
- **`arrival_offset`** - Time in milliseconds when the request should be sent
- **`mode`** - Request mode: `"interactive"` (low-latency, real-time) or `"batch"` (background processing). Defaults to `"interactive"`.
- **`priority`** - Priority level: `"low"` (1), `"mid"` (5), or `"high"` (10). Defaults to `"mid"`.
- **`body_json`** - Complete JSON request payload

See `tests/fixtures/scheduling/README.md` for detailed CSV format documentation.

### Interpreting Results

Workload definitions live under `tests/fixtures/scheduling/`, and the generated benchmark results are written to `tests/results/scheduling/` so they are accessible from the host machine.

The script sends each request at its configured arrival offset (in milliseconds), waits for the system to schedule and execute it, and then pulls the resulting log entries.

**Output Files:**

The script generates **two separate CSV files** plus visualization charts:

1. **`*_summary.csv`** - Compact aggregated metrics:
   - Request counts (total, successful, failed)
   - Error rate and SLO attainment rate
   - **TTFT (Time-to-First-Token)** - avg, p50, p95, p99
   - **TPOT (Time Per Output Token)** - avg, p50, p95, p99
   - **Total latency** - avg, p50, p95, p99

2. **`*_detailed.csv`** - Individual request data:
   - Each row represents one request with full details
   - Includes: request_id, mode, priority, model, TTFT, TPOT, tokens, latency, response text, errors

3. **`*.png`** - Latency visualization charts for quick inspection

Use `--latency-slo-ms` to tune the latency objective (in milliseconds) for SLO attainment calculations.

**To verify which mode was used for each request:**

Check the database for classification statistics:

```bash
docker compose exec logos-db psql -U postgres -d logosdb -c \
  "SELECT id, model_id,
   CASE WHEN classification_statistics IS NOT NULL THEN 'classification' ELSE 'direct' END as mode
   FROM log_entry WHERE id > 85 ORDER BY id DESC LIMIT 10;"
```

If `classification_statistics` is NULL, the request used direct model selection. If it contains data, classification ran and selected the model.

_The scheduling testing scaffolding was prepared with GPT-5 assistance._

# Test Server

The test instance runs at `logos-test.aet.cit.tum.de`. To access it you need:

1. **EduVPN** — activate the "MWN full-tunnel" profile via the [EduVPN portal](https://rad.eduvpn.lrz.de/vpn-user-portal/home).
2. **SSH access** — request access at [AET Request](https://request.aet.cit.tum.de/) using your TUM username and public SSH key. When filling in the free-text field, mention that you need access to the Logos project.

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

## Accessing the Database

The PostgreSQL database is not directly reachable from outside the server. You need to tunnel through SSH, which most database clients (e.g. DBeaver) support natively.

### DBeaver SSH Tunnel Configuration

In DBeaver, create a new PostgreSQL connection and configure the **SSH** tab as follows:

| Field | Value |
|-------|-------|
| Host/IP | `aetvm45.cit.tum.de` |
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
