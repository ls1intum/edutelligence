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
   
2. Insert initial Provider Configuration

   In docker-compose.yml, adjust the environment section of the logos-server 
   container to specify the initial LLM provider that Logos should connect to after startup.

   Example Configuration:
      ```
       environment:
         PROVIDER_NAME: azure
         BASE_URL: https://ase-se01.openai.azure.com/openai/deployments/
      ```

3. Build and Run Logos

   Now go to the root-directory of Edutelligence and execute the following commands:
   
   ```
   docker compose -f ./logos/docker-compose.yaml build
   ```
   
   and afterward
   
   ```
   docker compose -f ./logos/docker-compose.yaml up
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

```bash
docker compose exec logos-server \
  poetry run python logos/tests/support/scheduling/run_api_workload.py \
    --logos-key "YourLogosApiKey" \
    --workload logos/tests/fixtures/scheduling/sample_workload.csv \
    --api-base http://localhost:8080 \
    --latency-slo-ms 10000 \
    --output logos/tests/results/scheduling/api_benchmark.csv
```

Workload definitions live under `tests/fixtures/scheduling/`, and the generated benchmark CSVs are written to `tests/results/scheduling/` so they are accessible from the host machine.

The script sends each request at its configured arrival offset, waits for the system to schedule and execute it, and then pulls the resulting log entries. The output CSV contains a summary row (request counts, average TTFT, average latency, SLO attainment) followed by one row per request with the prompt, HTTP status, selected model/provider, TTFT, total latency, and the provider response text. Optional custom payloads can be provided via the `body_json` or `body_template` columns. Additionally, latency charts are written next to the CSV (PNG files) for quick visual inspection of the run. Use `--latency-slo-ms` to tune the latency objective (in milliseconds) for the summary calculations.

_The scheduling testing scaffolding was prepared with GPT-5 assistance._
