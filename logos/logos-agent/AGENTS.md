# AGENTS.md — logos-agent

Python 3.13 / FastAPI service that runs coding agents in isolated containers on serving capacity Logos is not otherwise using. See `README.md` for the architecture, isolation model, and API surface — the notes below are the non-obvious constraints.

## Non-obvious invariants

- **Isolation boundary**: the runner holds the Docker socket; session containers get no socket, no root, no capabilities, a read-only root filesystem, and memory/CPU/PID ceilings. That asymmetry is set in exactly one place: `app/docker_engine.py:create_session_container` — keep it that way.
- **Session network** is an *internal* bridge with no route off the host; the runner verifies this and refuses to start on a plain bridge. Session containers may only reach the model gateway.
- A session's model traffic goes through `logos-orchestrator`; sessions can be told to deploy their result to the dev environment and screenshot the pages they changed.
- **The finalizer commits on the base the preparation recorded**, not on a fresh fetch of the base branch: `prepare_checkout` writes the commit it checked out to `WORKSPACE/.session/base-sha`, and `finalize_checkout` re-anchors the session's branch on it — the working tree is that base plus the agent's edits, and anchoring it on the base's newer tip would present everything merged in the meantime as the session's deletions. The moved base is met at the commit instead: `commit_and_push` rebases the work onto the fetched tip, and a conflict there fails the session. A missing or not-a-commit record fails the finalizer; the record sits on the volume the agent can write, so it is validated, not trusted. The same guardrail on the tree: a push that deletes files the agent's transcript (`touched-files.txt`, written by the agent phase after the agent exits) does not show it editing is refused.

## Commands

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest            # asyncio_mode = "auto"
```

Python style matches the repo: black 120 cols, isort (black profile), flake8.
