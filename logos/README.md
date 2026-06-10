# Logos: LLM Engineering made easy

**Logos** is an LLM Engineering Platform that includes usage logging, billing, central resource management, policy-based model selection, scheduling, and monitoring.

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
| `docker-compose.yaml` | **Production** — pulls pre-built images from GHCR |
| `docker-compose.dev.yaml` | **Development** — builds images locally from source |

## Running the Service (Development)
To deploy Logos locally:

1. Clone the repository:

   ```bash
   git clone https://github.com/ls1intum/edutelligence/
   ```

2. Insert initial Provider Configuration

   In docker-compose.dev.yaml, adjust the environment section of the logos-server
   container to specify the initial LLM provider that Logos should connect to after startup.

   Example Configuration:
      ```
       environment:
         PROVIDER_NAME: azure
         BASE_URL: https://ase-se01.openai.azure.com/openai/deployments/
      ```

3. Build and Run Logos

   From the `logos/` directory:

   ```bash
   docker compose -f docker-compose.dev.yaml up --build
   ```

   After startup, Logos will print your initial root key in the logs—save this, as it is required for first login.

4. Access Web-UI

   Once running, the Logos UI is accessible at:
   ```
   http://localhost:18081/
   ```
   You can log in using the root key provided at startup.

5. Explore the API

   A full overview of available endpoints can be found at: https://logos.ase.cit.tum.de:8080/docs

## Scheduling & Capacity Management

Logos includes an independently toggleable subsystem for proactive worker management:

| Subsystem | Env Variable | Default | What it does |
|-----------|-------------|---------|-------------|
| **Capacity Planner** | `LOGOS_CAPACITY_PLANNER_ENABLED` | `true` | Background loop (30s cycles) that sleeps idle lanes, wakes lanes on demand, and tunes vLLM GPU memory utilization. |

Set to `false` to disable. Add to the `environment` section of `logos-server` in `docker-compose.yaml`:
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
docker compose exec logos-server \
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
docker compose exec logos-server \
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
docker compose exec logos-server \
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

## Accessing the API

The API is served on port `8080`. Note that a `GET /` returns 404 by design — the root path is not a valid endpoint. Use the `/docs` path to explore the API:

```
https://logos-test.aet.cit.tum.de:8080/docs
```

## Accessing the Admin UI

The Admin UI runs on port `9443`, but it is only accessible from within the chair network. You need to forward the port over SSH and add a temporary host alias so the TLS certificate is valid.

**Step 1 — open the tunnel** (keep this terminal open):

```bash
ssh -L 9443:127.0.0.1:9443 <yourtumkuerzel>@logos-test.aet.cit.tum.de
```

**Step 2 — add a local hosts entry:**

```bash
sudo sh -c 'echo "127.0.0.1 logos-test.aet.cit.tum.de" >> /etc/hosts'
```

**Step 3 — open the UI** at:

```
https://logos-test.aet.cit.tum.de:9443/
```

> [!NOTE]
> Use the domain, not `https://localhost:9443/` — the TLS certificate is issued for the hostname, not localhost.

> [!IMPORTANT]
> Remember to remove the `/etc/hosts` entry afterwards to avoid routing issues.

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
