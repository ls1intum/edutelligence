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
