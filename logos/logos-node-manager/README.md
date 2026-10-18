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

The socket is root on the host. "Security model" below says what that allows and how the container is limited.

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

## Security model

The manager controls the Docker engine of the host through the mounted socket. That socket is root on the host: a
process that can use it can start any container with any mount. A read-only mount does not change this, because the
engine API is not read-only. The manager cannot do its job without the socket, because its job is to run `docker compose`
for the worker. The risk is accepted for these reasons:

* The manager has no way in from the network. It publishes no port and runs no server. It is reached with
  `docker exec`, which needs access to `docker` on the host (root-equivalent anyway), and through the files in its state
  directory. Whoever can write there can queue a deployment of any tag that exists in the registry.
* Every command is an argument list and never goes through a shell. The command line checks a deployment id and a tag
  against strict patterns before it accepts a request. The free text of `--requested-by` is only stored in the record.
* The container sees little of the host: the worker directory (read-only), the Docker login of the host user
  (read-only), its own state directory and the socket. The worker directory includes the `.env` with the secrets of the
  worker, because Compose needs that file. No output of `docker compose config` and no environment is logged (see
  "Rules the code keeps").

The container gets nothing more than that. It starts with `no-new-privileges`, drops all Linux capabilities except
`DAC_OVERRIDE`, and has a read-only root filesystem with a 16 MB `/tmp`. `DAC_OVERRIDE` stays because the manager runs
as root and must read files of the deploy user, for example a `.env` with mode 600, and write a state directory that the
deploy user owns. Without it, root cannot do either. This hardening limits what a compromised manager can do inside its
own container. It does not limit what the socket allows. The smoke test runs the manager with the same options.

A socket proxy that allows only some API calls was considered and not added. It filters by URL and method, not by the
content of a request. The manager has to create containers, and a request to create one can mount the whole disk of the
host. A proxy would add a second container that holds the socket and would not remove the root access.

For operators:

* Use a registry account that can pull but not push for the `docker login` on the host. The manager can read the login
  file, and so can every user who can run `docker` on the host.
* Limit who can run `docker` and `docker exec` on the host, and who can write to the state directory. These users are
  root-equivalent with or without the manager.

For people who change the code:

* Do not publish a port or add a network listener.
* Do not start a command through a shell. Check every value that comes from outside before it reaches a command.
* Do not mount more of the host into the container, and do not add capabilities.

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
