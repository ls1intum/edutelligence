# Logos: LLM Engineering made easy

**Logos** is an LLM Engineering Platform that includes usage logging, billing, central resouce management, policy-based model selection, scheduling, and monitoring.

# Setup

## Prerequisites

- **Python 3.13**
- **Poetry** for dependency management
- **Docker** for containerization

## Installation

### Poetry

Install Poetry, if you haven't already:

```bash
pip install poetry
```

Ensure that you are using poetry version 2.0.0 or higher.

```bash
poetry --version
```

If you have poetry < 2.0.0 installed, please run

```bash
poetry self update
```

#### Dependencies

Activate the virtual environment and install the dependencies:

```bash
poetry env activate
poetry install
```

## Running the Service
To deploy Logos locally or on a server:

1. Clone the repository:

   ```bash
   git clone https://github.com/ls1intum/edutelligence/
   ```

2. Insert initial Provider Configuration

   In the docker-compose file, adjust the environment section of the logos-server
   container to specify the initial LLM provider that Logos should connect to after startup.

   Example Configuration:
      ```
       environment:
         PROVIDER_NAME: azure
         BASE_URL: https://ase-se01.openai.azure.com/openai/deployments/
      ```

3. Build and Run Logos

   Logos provides two docker-compose configurations:

   | File | Purpose |
   |------|---------|
   | `docker-compose.yaml` | **Production** - pulls pre-built images from GitHub Container Registry |
   | `docker-compose.dev.yaml` | **Development** - builds images locally from source |

   **For Production:**
   ```bash
   docker compose -f ./logos/docker-compose.yaml pull
   docker compose -f ./logos/docker-compose.yaml up -d
   ```

   **For Development:**
   ```bash
   docker compose -f ./logos/docker-compose.dev.yaml up -d --build
   ```

   After startup, Logos will print your initial root key in the logs—save this, as it is required for first login.

4. Access Web-UI

   Once running, the Logos UI is accessible at:
   ```
   https://logos.ase.cit.tum.de:8080/
   ```
   You can log in using the root key provided at startup.

5. Explore the API

   A full overview of available endpoints can be found at: https://logos.ase.cit.tum.de:8080/docs
   
## Scheduler Benchmarking

To evaluate scheduler behaviour against the running Logos API, replay a scripted workload via the `/v1` endpoint using the helper in `tests/support/scheduling/run_api_workload.py`.

A short guide on crafting compatible workload CSVs lives next to the sample workload in `tests/fixtures/scheduling/README.md`.

### Testing Classification vs Direct Model Selection

Logos supports two operational modes that can be benchmarked:

**1. Direct Model Selection (Scheduling Only)**

Test scheduling behavior with a specific model. Classification is skipped.

```bash
docker compose exec logos-server \
  poetry run python logos/tests/support/scheduling/run_api_workload.py \
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
  poetry run python logos/tests/support/scheduling/run_api_workload.py \
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
  poetry run python logos/tests/support/scheduling/run_api_workload.py \
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
