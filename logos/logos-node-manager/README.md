# Logos Node Manager

The node manager replaces the worker node container on a GPU host. It pulls the new image, starts the new container,
checks that the container comes up, and starts the previous version again if it does not. It runs as a container next to the worker, in the same compose project.

## What a deployment does

A deployment is one request to run a given image tag. The daemon takes requests one at a time, oldest first.

| Phase | What happens |
|---|---|
| `pulling` | Notes the running container, then pulls the new image. If the pull fails, nothing else happens and the running container is not touched. |
| `draining` | Reserved. This version passes through it without waiting. |
| `swapping` | If the new image differs from the running one, keeps the running image under the name `<image>:previous`. Then runs `docker compose up -d --no-deps` for the worker service. Compose recreates the container when its image or its configuration changed. If nothing changed, the deployment ends as `unchanged`. |
| `verifying` | Waits until the container is healthy and stays healthy for the stability window (60 s). It fails if the container exits, restarts, reports `unhealthy`, runs another image, or is not healthy after 10 minutes. |
| `rolling_back` | Runs the previous image again. It points the compose image name back at it and recreates the container without a pull, then runs the same check. If the recreation fails, it tries again after 5 s and once more after 10 s, three attempts in all: a replacement that was cut off can leave containers behind that make the first attempt fail. |

The result of a deployment is one of these:

| Outcome | Meaning | Exit code of `deploy --wait` |
|---|---|---|
| `succeeded` | The new container runs and is healthy. | 0 |
| `unchanged` | The container already ran the requested image. | 0 |
| `rolled_back` | The new container failed, or the manager itself failed three times in a row after the swap. The previous version runs again. | 10 |
| `failed` | The deployment failed. See `failure` in the record: `pull_failed`, `swap_failed`, `verify_failed` (no previous version to restore), `rollback_failed`, `internal_error`. | 11 |

`deploy --wait` ends with exit code 12 if the wait runs out before the deployment ends. The deployment itself keeps
running. Attach to it again with `node-manager wait <id>`.

If the manager itself fails three times in a row in one phase, for example because Docker does not answer, it gives up
on that phase. Before the swap nothing was replaced, so the deployment ends as `failed` (`internal_error`). From the
swap on, the worker may run an image that nobody checked, so the manager restores the previous version first and the
deployment ends as `rolled_back` (`internal_error`). The rollback has three attempts of its own. If they fail as well,
the deployment ends as `failed` (`rollback_failed`) and every image stays on the host.

The log of a failed container is saved in the record before the rollback removes the container. `deploy --wait`
prints it unless it is called with `--no-logs`.

### What the check can see

The check uses what Docker shows from outside: the container runs, its health check passes, it does not restart, and it
runs the expected image. The health check of the worker only shows that the worker started and answers on its port. It
does not show that the worker connected to the orchestrator or loaded its models. The manager has no way to ask the
worker for that yet.

### Images on the host

Docker keeps every image it has pulled, so a host that is updated often fills up. When a deployment has ended, the
manager removes the two images it no longer needs:

* the image that the name `previous` pointed to before this deployment, which is now two versions old;
* the image that the deployment pulled, if no container runs it. This is the failed release after a rollback or a
  failed swap.

Nothing is removed before the end, because a rollback may still need the images. The previous version always stays.
After a failed rollback every image stays, so that a person can repair the host by hand. A deployment that ends at a
failed pull, or as `unchanged`, removes nothing.

The manager removes an image by its ID (`docker rmi`), so an image that a container uses, or that has more than one
name, stays. A problem during the removal is logged and does not change the result of the deployment.

## Use

On a worker host, the manager is the service `logos-node-manager` in `logos-workernode/docker-compose.yml`. It belongs
to the compose profile `node-manager`, so it only exists on hosts that enable that profile:

```bash
# in the .env of the worker
COMPOSE_PROFILES=node-manager
```

The deploy workflows write this line for every worker whose matrix entry has `node-manager: true`.

The image of the service is `${REGISTRY}/logos-node-manager`. The default registry is the public GHCR mirror, which does
not have this image, so set `REGISTRY` in the `.env` of the worker to the deployment registry (`<registry>/logos`). The
deploy workflows write it.

The service needs three things from the host:

* the Docker socket, so it can run `docker`;
* the worker directory, mounted at the same path as on the host (Compose turns relative bind mounts into absolute host
  paths before it sends them to the Docker engine);
* the Docker login of the host user, mounted read-only, so it can pull from a registry that needs a login. Run
  `docker login` on the host first. The mount is declared so that Docker does not create the file when it is missing:
  the service then fails to start with a clear message. A new `docker login` replaces the file, and a mounted file keeps
  showing the old one. After each login, recreate the service with
  `docker compose up -d --force-recreate logos-node-manager`. The deploy workflows do this on every run.

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

The tag `previous` cannot be deployed. The manager uses the local name `<image>:previous` for the version that ran
before, and it moves that name to the running image before the swap. `deploy` refuses the tag with exit code 2.

## State

The state directory is `<worker directory>/node-manager`. It holds one JSON file per deployment in `deployments/` and a
`heartbeat` file. Every write replaces the file atomically. The record is the memory of the manager: if the manager
stops in the middle of a deployment, for example because its own container is recreated, the next start continues from
the recorded phase. Every step can be repeated. The manager keeps the 30 newest finished records. A file in
`deployments/` whose name is not a valid deployment id is ignored and logged once.

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
* A command that runs out of time is stopped together with every process it started: the group gets SIGTERM, and
  SIGKILL after 10 s. No old command goes on while the manager moves to the next step. What the Docker engine has
  already begun, for example stopping a container, goes on and is not undone. The rollback tries again for this reason.
* The manager never runs a global image prune. When a deployment has ended it removes only the images listed under
  "Images on the host", by ID.

## Tests

```bash
cd logos/logos-node-manager
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
```

The unit tests need no Docker. `FakeDocker` in `tests/conftest.py` simulates the engine.

`tests/smoke/run-smoke.sh` runs the real manager container against a dummy worker, with real Docker, a local registry
and no GPU. It covers a normal deployment, a broken release that is rolled back, a tag that does not exist, a deployment
with nothing to change, a manager that restarts in the middle of a deployment, and a later release that removes the
image from two versions back. After each of them it counts the images on the host, to see that none is left without a
purpose. It needs a running Docker engine and network access to pull the base images.

## Limits of this version

* Running requests are not waited for. A deployment replaces the container at once, as a manual `docker compose up`
  does.
* The removal of old images starts after the result is saved. `deploy --wait` can return a moment before it ends, and a
  manager that stops in between leaves those images on the host. `docker rmi` removes them.
* The image is published to the project registry only, not to the public GHCR mirror.
