# Logos Node Manager

The node manager replaces the worker node container on a GPU host. It pulls the new image, starts the new container,
checks that the container comes up, and starts the previous version again if it does not. It runs as a container next to the worker, in the same compose project.

## What a deployment does

A deployment is one request to run a given image tag. The daemon takes requests one at a time, oldest first.

| Phase | What happens |
|---|---|
| `pulling` | Notes the running container and keeps its image under the name `<image>:previous`. Pulls the new image. If the pull fails, nothing else happens and the running container is not touched. |
| `draining` | Reserved. This version passes through it without waiting. |
| `swapping` | Runs `docker compose up -d --no-deps` for the worker service. Compose recreates the container when its image or its configuration changed. If nothing changed, the deployment ends as `unchanged`. |
| `verifying` | Waits until the container is healthy and stays healthy for the stability window (60 s). It fails if the container exits, restarts, reports `unhealthy`, runs another image, or is not healthy after 10 minutes. |
| `rolling_back` | Runs the previous image again. It points the compose image name back at it and recreates the container without a pull, then runs the same check. |

The result of a deployment is one of these:

| Outcome | Meaning | Exit code of `deploy --wait` |
|---|---|---|
| `succeeded` | The new container runs and is healthy. | 0 |
| `unchanged` | The container already ran the requested image. | 0 |
| `rolled_back` | The new container failed. The previous version runs again. | 10 |
| `failed` | The deployment failed. See `failure` in the record: `pull_failed`, `swap_failed`, `verify_failed` (no previous version to restore), `rollback_failed`, `internal_error`. | 11 |

`deploy --wait` ends with exit code 12 if the wait runs out before the deployment ends. The deployment itself keeps
running. Attach to it again with `node-manager wait <id>`.

The log of a failed container is saved in the record before the rollback removes the container. `deploy --wait`
prints it unless it is called with `--no-logs`.

### What the check can see

The check uses what Docker shows from outside: the container runs, its health check passes, it does not restart, and it
runs the expected image. The health check of the worker only shows that the worker started and answers on its port. It
does not show that the worker connected to the orchestrator or loaded its models. The manager has no way to ask the
worker for that yet.

## Use

On a worker host, the manager is the service `logos-node-manager` in `logos-workernode/docker-compose.yml`. It belongs
to the compose profile `node-manager`, so it only exists on hosts that enable that profile:

```bash
# in the .env of the worker
COMPOSE_PROFILES=node-manager
```

The deploy workflows write this line for every worker whose matrix entry has `node-manager: true`.

The service needs three things from the host:

* the Docker socket, so it can run `docker`;
* the worker directory, mounted at the same path as on the host (Compose turns relative bind mounts into absolute host
  paths before it sends them to the Docker engine);
* the Docker login of the host user, mounted read-only, so it can pull from a registry that needs a login. Run
  `docker login` on the host first. The mount is declared so that Docker does not create the file when it is missing:
  the service then fails to start with a clear message.

Commands (run them with `docker exec logos-node-manager node-manager …`):

| Command | Purpose |
|---|---|
| `run` | Start the daemon. This is the main process of the container. |
| `deploy --id ID --tag TAG [--wait] [--timeout S] [--requested-by TEXT] [--no-logs]` | Queue a deployment. With `--wait`, follow it and exit with its result. Repeating an id attaches to the existing deployment. |
| `wait ID [--timeout S]` | Follow a deployment that is already queued. |
| `status [ID] [--json]` | Show a deployment. Without an id, the latest one. |
| `ping` | Exit 0 if the daemon is alive. The container health check uses it. |

The requested tag reaches Compose as the `IMAGE_TAG` process variable. A process variable beats the `.env` file, so a
later rewrite of that file cannot change what an earlier request deploys.

## State

The state directory is `<worker directory>/node-manager`. It holds one JSON file per deployment in `deployments/` and a
`heartbeat` file. Every write replaces the file atomically. The record is the memory of the manager: if the manager
stops in the middle of a deployment, for example because its own container is recreated, the next start continues from
the recorded phase. Every step can be repeated. The manager keeps the 30 newest finished records.

## Configuration

All settings are environment variables with the prefix `NODE_MANAGER_`.

| Variable | Default | Meaning |
|---|---|---|
| `PROJECT_DIR` | `/opt/logos-workernode` | The compose project of the worker. |
| `COMPOSE_FILE`, `ENV_FILE` | `<PROJECT_DIR>/docker-compose.yml`, `<PROJECT_DIR>/.env` | |
| `PROJECT_NAME` | derived from the directory name | The compose project name. |
| `SERVICE`, `CONTAINER` | `logos-workernode` | The worker service and its container. |
| `STATE_DIR` | `<PROJECT_DIR>/node-manager` | |
| `PULL_TIMEOUT_S` | 1800 | |
| `SWAP_TIMEOUT_S` | 300 | The old container can take 2 minutes to stop. |
| `VERIFY_TIMEOUT_S` | 600 | How long to wait for the first healthy state. |
| `ROLLBACK_VERIFY_TIMEOUT_S` | 300 | |
| `STABILITY_WINDOW_S` | 60 | How long the container must stay healthy. 0 switches the wait off. |
| `POLL_INTERVAL_S`, `LOOP_INTERVAL_S` | 5, 2 | |
| `DRAIN_ENABLED` | false | Reserved. It has no effect yet. |
| `LOG_LEVEL` | `INFO` | |

A missing, malformed or non-positive timeout falls back to its default.

## Rules the code keeps

* Only `docker compose` creates the worker container, so Compose stays the one definition of its GPUs, volumes and
  limits.
* `docker compose config` is only called with `--images`. Its normal output contains the resolved environment, which
  holds secrets. No output of it is logged, and neither is the environment of a command.
* The manager never runs a global image prune. After a success it removes only the image that the name `previous`
  pointed to before the deployment, if no container uses it.

## Tests

```bash
cd logos/logos-node-manager
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
```

The unit tests need no Docker. `FakeDocker` in `tests/conftest.py` simulates the engine.

`tests/smoke/run-smoke.sh` runs the real manager container against a dummy worker, with real Docker, a local registry
and no GPU. It covers a normal deployment, a broken release that is rolled back, a tag that does not exist, a deployment
with nothing to change, and a manager that restarts in the middle of a deployment. It needs a running Docker engine and
network access to pull the base images.

## Limits of this version

* Running requests are not waited for. A deployment replaces the container at once, as a manual `docker compose up`
  does.
* The image is published to the project registry only, not to the public GHCR mirror.
