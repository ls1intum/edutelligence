# logos-orchestrator

Python FastAPI service — LLM gateway, proxy, scheduling, and capacity management.

See the root [README](../README.md) for the full project overview.

## Model-provider benchmarks

The internal benchmark runner reserves the selected worker/model lanes, drains
existing traffic, and allows only authenticated benchmark requests through those
lanes until job cleanup. A batch retains ownership between runs. Failed lane
preparation applies requested serving overrides before another startup attempt.

See [Configurable model benchmarks](docs/benchmark-configuration.md) for the API,
reservation lifecycle, configuration persistence, implementation entry points,
and Dev verification steps. The guide also explains the single-run charts and
confirmation flow in the web application.

The [screenshot walkthrough](../docs/admin/model-benchmarks.md) shows
single-run results and the confirmation dialog on desktop and mobile.
