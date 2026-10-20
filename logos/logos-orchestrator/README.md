# logos-orchestrator

Python FastAPI service — LLM gateway, proxy, scheduling, and capacity management.

See the root [README](../README.md) for the full project overview.

## Model-provider benchmarks

The orchestrator reserves the selected worker/model pair, including lanes created
after the reservation. The internal benchmark runner drains
existing traffic, and allows only authenticated benchmark requests through those
lanes until job cleanup. A batch retains ownership between runs. Failed lane
preparation applies requested serving overrides before another startup attempt.

See [Configurable model benchmarks](docs/benchmark-configuration.md) for the API,
reservation lifecycle, configuration persistence, implementation entry points,
and Dev verification steps.

The [screenshot walkthrough](../docs/admin/model-benchmarks.md) shows
configuration, confirmation, results and GPU limits in the web application.

## Nightly benchmarks

The application runs calibration first, then opt-in benchmarks if time remains.
A shared 15-second loop drives both. `LOGOS_MAINTENANCE_MAX_NODES` limits simultaneous
maintenance workers, including manual starts. It defaults to `1`; `2` permits two
workers in parallel. Calibration and benchmark phases remain separate.
Schedules default to disabled and are stored in PostgreSQL by the webservice's
`065_nightly_benchmarks.xml` changelog. It also adds durable calibration and
manual benchmark claims, keyed by provider and job. Worker confirmation is
required before a calibration claim is released. Schema preconditions adopt existing tables
when upgrading from earlier changeSet IDs. All changeSets provide rollbacks.

The scheduler admits at most two enabled model/worker pairs per Berlin date.
A cluster lock owns each bounded parallel batch, and persisted date claims retain the quota
across restarts. Worker recovery takes priority over admission. The nightly
path reuses the existing GuideLLM job, inference logging and result storage.

| Module | Responsibility |
|---|---|
| `benchmarks/maintenance.py` | Shared admission and confirmed calibration completion |
| `benchmarks/nightly.py` | Time policy, progress watchdog and fixed parameter plan |
| `benchmarks/nightly_scheduler.py` | Pair rotation, worker preparation and restoration |
| `benchmarks/nightly_store.py` | Persistent opt-in, daily quota, cluster lock and recovery journal |
| `benchmarks/progress.py` | Measured response progress; excludes transport heartbeats |
| `benchmarks/reservations.py` | Worker/model ownership and authenticated benchmark requests |
| `routers/nightly_benchmarks.py` | Internal status and activation API |

See the [nightly benchmark guide](../docs/admin/nightly-benchmarks.md) for the complete
policy, operator workflow and test commands. See
[configurable benchmarks](docs/benchmark-configuration.md) for manual runs.
