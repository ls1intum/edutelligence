# AGENTS.md — logos-agent

Python 3.13 / FastAPI service that runs coding agents in isolated containers on serving capacity Logos is not otherwise using. See `README.md` for the architecture, isolation model, and API surface — the notes below are the non-obvious constraints.

## Non-obvious invariants

- **Isolation boundary**: the runner holds the Docker socket; session containers get no socket, no root, no capabilities, a read-only root filesystem, and memory/CPU/PID ceilings. That asymmetry is set in exactly one place: `app/docker_engine.py:create_session_container` — keep it that way.
- **Session network** is an *internal* bridge with no route off the host; the runner verifies this and refuses to start on a plain bridge. Session containers may only reach the model gateway.
- A session's model traffic goes through `logos-orchestrator`; sessions can be told to deploy their result to the dev environment and screenshot the pages they changed.

## Commands

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest            # asyncio_mode = "auto"
```

Python style matches the repo: black 120 cols, isort (black profile), flake8.
