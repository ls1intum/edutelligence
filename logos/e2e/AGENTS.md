# AGENTS.md — logos/e2e

GPU-less end-to-end suite in four tiers. See `README.md` for the tier table and the GPU-simulation rationale.

Key facts for agents:

- Nothing in the worker or orchestrator is stubbed; only the layer *below* the worker is simulated (`nvidia-smi`, `nvcc`, the `vllm` binary) via `gpusim`, because every GPU-compatibility decision is read from that text boundary.
- **The stack is started separately on purpose** (`harness.stack.compose up`) — the tests skip with instructions when it is down; they do not own its lifecycle. Don't add setup/teardown to the suites.
- Tier 4 (Playwright) lives in `../logos-ui/e2e` and goes through Traefik rather than straight at the UI container — production serves UI and API on one origin, and separate origins would hide CORS/cookie/same-origin-WebSocket problems.

```bash
cd logos/e2e
uv venv .venv && uv pip install --python .venv/bin/python -e .
uv pip install --python .venv/bin/python -r ../logos-workernode/requirements.txt
.venv/bin/python -m pytest tests/gpu -v                     # tier 1, no Docker
.venv/bin/python -m harness.stack.compose up                # tiers 2+3
.venv/bin/python -m pytest tests/node tests/client -v
.venv/bin/python -m harness.stack.compose down
```
