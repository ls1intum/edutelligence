# logos-orchestrator

Python FastAPI service — LLM gateway, proxy, scheduling, and capacity management.

See the root [README](../README.md) for the full project overview.

## Nightly benchmarks

The application owns the nightly scheduler. It replaces the automatic
calibration maintenance timer; explicit calibration remains available.
Schedules default to disabled and are stored in PostgreSQL by the webservice's
`057_nightly_benchmarks.xml` migration.

The scheduler admits at most two enabled model/worker pairs per Berlin date.
A cluster lock serializes execution, and persisted date claims retain the quota
across restarts. Worker recovery takes priority over admission. The nightly
path reuses the existing GuideLLM job, inference logging and result storage.

| Module | Responsibility |
|---|---|
| `benchmarks/nightly.py` | Time policy, progress watchdog and fixed parameter plan |
| `benchmarks/nightly_scheduler.py` | Pair rotation, worker preparation and restoration |
| `benchmarks/nightly_store.py` | Persistent opt-in, daily quota, cluster lock and recovery journal |
| `benchmarks/progress.py` | Measured response progress; excludes transport heartbeats |
| `benchmarks/reservations.py` | Worker/model ownership and authenticated benchmark requests |
| `routers/nightly_benchmarks.py` | Internal status and activation API |

See the [nightly benchmark guide](docs/nightly-benchmarks.md) for the complete
policy, operator workflow and test commands. See
[configurable benchmarks](docs/benchmark-configuration.md) for manual runs.
