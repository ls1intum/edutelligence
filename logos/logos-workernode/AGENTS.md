# AGENTS.md — logos-workernode

Python control plane for GPU worker nodes: starts one vLLM lane per configured model, holds a websocket bridge to `logos-orchestrator` (`logosnode_registry.py` on the orchestrator side), reports runtime/device/lane status for warm/cold scheduling, and auto-calibrates per-model VRAM profiles.

Sources of truth:

- `README.md` — overview, configuration split (`.env` credentials vs `config.yml` hardware — never mix them), chat templates.
- `LANES.md` — lane operations (vLLM lane lifecycle).
- `TESTING.md` — benchmark and runbook commands.
- `logos_worker_node/models.py` — exact request/response schemas (`admin_api.py` no longer exists; schemas live in `models.py` alone).

If any historical note conflicts with runtime behavior, follow the code and the docs above.

## Notes for agents

- Calibration results persist in the worker's state directory and flow to Logos over the existing websocket heartbeat — no extra worker-side configuration.
- Tests run through the shared `logos_test.yml` CI job together with the orchestrator suite; a change touching both needs both green.
- The `logos/e2e` tier-1 suite drives the real `logos_worker_node` against simulated GPUs (`gpusim`) — run it when changing GPU-compatibility decisions (`../e2e/AGENTS.md`).
