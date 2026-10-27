# Logos Node Manager

The node manager replaces the worker node container on a GPU host. It pulls the new image, starts the new container,
checks that the container comes up, and starts the previous version again if it does not. It runs as a container next to the worker, in the same compose project.

On a host that drains, the manager first asks the orchestrator to cordon the node. A cordoned node gets no new
requests, so the requests that run on it finish before the container goes. See "Draining" below.

## What a deployment does

A deployment is one request to run a given image tag. The daemon takes requests one at a time, oldest first.

| Phase | What happens |
|---|---|
| `pulling` | Notes the running container, then pulls the new image. If the pull fails, nothing else happens and the running container is not touched. |
| `draining` | Asks the orchestrator to cordon the node and waits until the node has drained (see "Draining"). Without `DRAIN_ENABLED`, or without an orchestrator to ask, the phase passes at once. |
| `swapping` | If the new image differs from the running one, keeps the running image under the name `<image>:previous`. Then runs `docker compose up -d --no-deps` for the worker service. Compose recreates the container when its image or its configuration changed. If nothing changed, the deployment ends as `unchanged`. |
| `verifying` | Waits until the container is healthy and stays healthy for the stability window (60 s). It fails if the container exits, restarts, reports `unhealthy`, runs another image, or is not healthy after `VERIFY_TIMEOUT_S` (10 minutes by default, 11 minutes in the worker compose file). After a drain it also waits until the orchestrator sees the new worker (see "Draining"). |
| `rolling_back` | Runs the previous image again. It points the compose image name back at it and recreates the container without a pull, then runs the same check. If the recreation fails, it tries again after 5 s and once more after 10 s, three attempts in all: a replacement that was cut off can leave containers behind that make the first attempt fail. |

The result of a deployment is one of these:

| Outcome | Meaning | Exit code of `deploy --wait` |
|---|---|---|
| `succeeded` | The new container runs and is healthy. | 0 |
| `unchanged` | The container already ran the requested image. | 0 |
| `rolled_back` | The new container failed, or the manager itself failed three times in a row after the swap. The previous version runs again. | 10 |
| `failed` | The deployment failed. See `failure` in the record: `pull_failed`, `drain_timeout` (the node did not drain), `drain_blocked` (the node never got its turn), `swap_failed`, `verify_failed` (no previous version to restore), `rollback_failed`, `internal_error`. | 11 |

`deploy --wait` ends with exit code 12 if the wait runs out before the deployment ends. The deployment itself keeps
running. Attach to it again with `node-manager wait <id>`. `deploy --until-pulled` ends with exit code 0 as soon as the
image is on the host: that code says the pull worked, not how the deployment ends. A deployment that is already over
returns its own exit code, and a failed pull returns 11.

If the manager itself fails three times in a row in one phase, for example because Docker does not answer, it gives up
on that phase. Before the swap nothing was replaced, so the deployment ends as `failed` (`internal_error`). From the
swap on, the worker may run an image that nobody checked, so the manager restores the previous version first and the
deployment ends as `rolled_back` (`internal_error`). The rollback has three attempts of its own. If they fail as well,
the deployment ends as `failed` (`rollback_failed`) and every image stays on the host.

The log of a failed container is saved in the record before the rollback removes the container. `deploy --wait`
prints it unless it is called with `--no-logs`.

### Draining

A deployment that drains does not cut the requests that run on the node. The manager works with the orchestrator,
because only the orchestrator can keep new requests from reaching the node, and it sees every request on its way to the
node.

1. The manager asks the orchestrator for the cordon of its node. The orchestrator knows the node from the key of the
   worker (`NODE_KEY`), so the manager can cordon its own node and no other.
2. The orchestrator grants the cordon to one node at a time. If another node is being replaced, or this node runs a
   calibration session, the manager asks again every `POLL_INTERVAL_S`. This goes on until the cordon is granted or
   `TURN_TIMEOUT_S` (2 hours) is over. In that case the deployment ends as `failed` (`drain_blocked`), and the
   container is not touched. The node serves as usual while it waits.
3. A cordoned node gets no new requests. The scheduler sends them to another node that serves the model. If no other
   connected node serves a model, its requests wait in the queue of the orchestrator until the node is back. They wait for
   20 minutes, or for the `timeout_s` of the client if the client sets one. The capacity planner places nothing on a
   cordoned node, and no calibration starts on it.
4. The manager asks until the node has drained. A node has drained when the orchestrator tracks no request for it (this
   includes a request that is scheduled but has not reached the worker) and the worker reports none, for 10 s in a row.
   Every call also renews the cordon, and takes it again if the orchestrator forgot it.
5. If the node has not drained after `DRAIN_TIMEOUT_S` (15 minutes from the grant), the manager gives the cordon back.
   The deployment ends as `failed` (`drain_timeout`). The running container was not touched, and it serves again.
6. When the node has drained, the swap and the checks follow. The cordon stays until the deployment ends, and then the
   manager gives it back, whatever the outcome. A cordon that its manager no longer renews expires after 30 minutes.
7. After the Docker checks, the manager waits until the orchestrator sees the new worker: connected through a new
   session, with its first status. If that does not happen within `RECONNECT_TIMEOUT_S` (5 minutes), the deployment is
   rolled back.

The record keeps the times of the drain, so a restart of the manager does not extend a limit. The events name what the
node waits for, for example the node that holds the cordon, or the number of requests that still run. That number is the
larger of the two counts, not their sum: the orchestrator tracks a request from its scheduling to its end, so a request
that runs on the worker is in both counts. The orchestrator alone knows a request that is scheduled but has not reached
the worker, and the worker alone knows one the orchestrator lost track of, for example after its restart. The record
keeps the number of requests the node still had when the cordon was granted. No new request arrives after that, so these
are the requests the drain waited for. The record also lists the models that no other node could serve while this node
was cordoned. Their requests waited for this node.

The manager skips the drain and replaces the container as before, with a note "draining skipped" in the record, if it
cannot ask the orchestrator: the address or the key is missing, the orchestrator does not know the endpoint (an older
version) or the key, or it did not answer for `ORCHESTRATOR_RETRY_WINDOW_S` (2 minutes). An orchestrator problem must not
stop the deployments that may repair it. `DRAIN_ENABLED=false` switches the whole phase off.

### Reports

When a deployment has ended, the manager tells the orchestrator how, and the orchestrator notifies the Logos admins in
the web application (the bell in the header). This closes the gap of a node that drains: its job is green when the image
is pulled, and what happens later on the host would otherwise show up in the next run only.

Only the ending is reported, never the phases in between. Those stay in the record (`node-manager status`).

| Outcome | Notification | Content |
|---|---|---|
| `succeeded` | `deployment` | The tag, the node, how long the drain took, and how many requests were still running when the node was cordoned. |
| `rolled_back` | `deployment_failed` | The reason, and that the previous version runs again. |
| `failed` | `deployment_failed` | The reason, for example `drain_timeout` or `pull_failed`. A `rollback_failed` says that the node needs manual action. |
| `unchanged` | `deployment` | The container already ran the image, so nothing was replaced. It is reported all the same: an admin who waits for the result of a deployment should get one, and silence would look like a failure. |

The notification goes to the role Logos admin, one per node and deployment. A rollout over several nodes therefore sends
one notification per node.

* There is no switch. The manager reports whenever it has `ORCHESTRATOR_URL` and `NODE_KEY`, with or without the drain.
  Without them it cannot reach the orchestrator, and it logs once at the start that nothing is reported.
* The call is `POST /logosdb/providers/logosnode/node-maintenance/report`. The orchestrator knows the node from the key,
  so the manager can only report for its own node. A repeated report of the same deployment is answered with
  `duplicate`, and sends nothing.
* The report is made after the record says the deployment is over, and it never changes the outcome. An orchestrator that
  does not answer is asked again for 30 seconds, so that a report does not hold up the next deployment for long. After
  that the report is not tried again before the next start of the manager. The record keeps `reported_at` once the orchestrator has accepted it, so a stop between the
  end and the report does not lose it. The manager reports an ending again after a restart only for one hour. This keeps
  the old records from being announced all at once when a manager that did not report yet is updated.

### What the check can see

The check uses what Docker shows from outside: the container runs, its health check passes, it does not restart, and it
runs the expected image. The health check of the worker only shows that the worker started and answers on its port. It
does not show that the worker connected to the orchestrator or loaded its models.

On a host that drains, the manager also asks the orchestrator whether the new worker connected (see "Draining"). It does
not compare the version that the worker reports, because the check of the image ID already shows which image runs. It
does not wait for the models: the capacity planner loads them when requests ask for them.

### Images on the host

Docker keeps every image it has pulled, so a host that is updated often fills up. When a deployment has ended, the
manager removes the two images it no longer needs:

* the image that the name `previous` pointed to before this deployment, which is now two versions old;
* the image that the deployment pulled, if no container runs it. This is the failed release after a rollback or a
  failed swap.

Nothing is removed before the end, because a rollback may still need the images. The previous version always stays.
After a failed rollback every image stays, so that a person can repair the host by hand. A deployment that ends at a
failed pull, or as `unchanged`, removes nothing. A deployment that ends at the drain (`drain_timeout`, `drain_blocked`)
removes the image it pulled, because no container runs it. The next try pulls it again.

The manager removes an image by its ID (`docker rmi`), so an image that a container uses, or that has more than one
name, stays. A problem during the removal is logged and does not change the result of the deployment.

The manager does not remove its own image. The deploy workflow does this in the step "Update node manager". The step
notes the ID of the image that the running manager uses. After the pull, only this ID identifies the old image. When the
new manager answers `node-manager ping`, the step removes the old image with `docker rmi`. If the new manager does not
start, the old image stays on the host.

A problem during the removal does not fail the step. A host without the deploy workflow keeps its old manager images.
Remove them by ID with `docker rmi`.

## Use

On a worker host, the manager is the service `logos-node-manager` in `logos-workernode/docker-compose.yml`. It belongs
to the compose profile `node-manager`, so it only exists on hosts that enable that profile:

```bash
# in the .env of the worker
COMPOSE_PROFILES=node-manager
```

The deploy workflows write this line for every worker whose matrix entry has `node-manager: true`. They also write
`NODE_MANAGER_DRAIN_ENABLED` for it: `true` if the entry has `drain: true`, `false` otherwise. With `drain: true` the
job of the worker ends as soon as the image is on the host (`deploy --until-pulled`), and the drain, the swap and the
checks go on there. The orchestrator then keeps at most one node out of service, because the matrix of the workflow can no
longer do it. A worker without `drain: true` is followed to its end (`deploy --wait`) and replaces its container at
once. Give every worker of a workflow `drain: true`, or put the workers without it first: a worker without it does not
wait for a node that still drains. The next run prints how the last deployment of the host ended.

The image of the service is `${REGISTRY}/logos-node-manager`. The default registry is the public GHCR mirror, which
carries the image of `main` (tag `latest`). The deploy workflows set `REGISTRY` in the `.env` of the worker to the
deployment registry (`<registry>/logos`). Set it there as well to pull a version tag or a pull request build, which the
mirror does not carry.

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
| `deploy --id ID --tag TAG [--wait \| --until-pulled] [--timeout S] [--requested-by TEXT] [--no-logs]` | Queue a deployment. With `--wait`, follow it and exit with its result. With `--until-pulled`, follow it until the image is on the host and exit then. Repeating an id attaches to the existing deployment. |
| `wait ID [--timeout S]` | Follow a deployment that is already queued. |
| `status [ID] [--json] [--logs]` | Show a deployment with its events. Without an id, the latest one. `--logs` adds the log of a failed container. |
| `ping` | Exit 0 if the daemon is alive. The container health check uses it. |

The requested tag reaches Compose as the `IMAGE_TAG` process variable. A process variable beats the `.env` file, so a
later rewrite of that file cannot change what an earlier request deploys.

The tag `previous` cannot be deployed. The manager uses the local name `<image>:previous` for the version that ran
before, and it moves that name to the running image before the swap. `deploy` refuses the tag with exit code 2.

## State

The state directory is `<worker directory>/node-manager`. It holds one JSON file per deployment in `deployments/` and a
`heartbeat` file. Every write replaces the file atomically. The record is the memory of the manager: if the manager
stops in the middle of a deployment, for example because its own container is recreated, the next start continues from
the recorded phase. Every step can be repeated. The record also holds the events of the deployment and, after a
failure, the end of the log of the failed container. This is where to look when a deployment ended after the job that
asked for it, and `docker logs logos-node-manager` is gone because a later run recreated the service. The manager keeps
the 30 newest finished records. A file in
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
| `VERIFY_TIMEOUT_S` | 600 | How long to wait for the first healthy state. The worker compose file sets 660: it must stay at least 35 s above the start period of the worker health check (10 minutes). |
| `ROLLBACK_VERIFY_TIMEOUT_S` | 300 | |
| `STABILITY_WINDOW_S` | 60 | How long the container must stay healthy. 0 switches the wait off. |
| `POLL_INTERVAL_S`, `LOOP_INTERVAL_S` | 5, 2 | |
| `DRAIN_ENABLED` | false | Whether a deployment drains the node before it replaces the container (see "Draining"). It needs `ORCHESTRATOR_URL` and `NODE_KEY`. The worker compose file sets it from `NODE_MANAGER_DRAIN_ENABLED` in the `.env` of the worker. |
| `ORCHESTRATOR_URL`, `NODE_KEY` | empty | The address of the orchestrator and the key of the worker. The worker compose file passes `LOGOS_URL` and `LOGOS_API_KEY` of the `.env`. The drain needs them, and the report of the end of a deployment (see "Reports") as well. |
| `DRAIN_TIMEOUT_S` | 900 | How long the node may take to drain, counted from the grant of the cordon. |
| `TURN_TIMEOUT_S` | 7200 | How long the manager waits for the cordon while another node is being replaced. |
| `ORCHESTRATOR_RETRY_WINDOW_S` | 120 | How long an orchestrator that does not answer is asked again before the drain is skipped. |
| `ORCHESTRATOR_TIMEOUT_S` | 15 | The time limit of one call to the orchestrator. |
| `RECONNECT_TIMEOUT_S` | 300 | How long the new worker may take to show up at the orchestrator after the Docker checks passed. |
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
* The container is replaced only after a fresh answer of the orchestrator that the node has drained. The record is saved
  with that answer before the swap begins.
* A deployment that held the cordon gives it back on every ending, before the record says it is over. The key of the
  node is sent in the body of a request and is never written to a log or to a record.
* A report of the ending is made after the record is over and never changes the outcome. The record keeps when the
  orchestrator accepted it, so an ending is reported once.

## Security model

The manager controls the Docker engine of the host through the mounted socket. That socket is root on the host: a
process that can use it can start any container with any mount. A read-only mount does not change this, because the
engine API is not read-only. The manager cannot do its job without the socket, because its job is to run `docker compose`
for the worker. The risk is accepted for these reasons:

* The manager has no way in from the network. It publishes no port and runs no server. It is reached with
  `docker exec`, which needs access to `docker` on the host (root-equivalent anyway), and through the files in its state
  directory. Whoever can write there can queue a deployment of any tag that exists in the registry.
* The only line out is the HTTPS call to the orchestrator for the drain. The manager authenticates with the key of the
  worker, which Compose passes in its environment. The container can read the `.env` with that key anyway, so it gains no
  secret, and the key lets it cordon its own node only. A person with the key can do the same from any machine, as they
  could already connect as the worker.
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
* Do not write the key of the node, or a request that carries it, to a log or a record.
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

Without the drain (`DRAIN_ENABLED` false, or no orchestrator to ask), running requests are not waited for. A deployment
replaces the container at once, as a manual `docker compose up` does. With the drain:

* **The cordon lives in the memory of the orchestrator.** A restart of the orchestrator forgets it. The manager asks
  again and never replaces the container without a fresh answer that the node has drained. If the restart comes while
  the container is replaced or checked, another node can start its deployment at that time, and two nodes are out of
  service for a while.
* **A model that only this node serves has no node during the deployment.** Its requests wait for the node, for up to
  20 minutes or the `timeout_s` of the client, and then fail with a 503. The wait is the rest of the drain, the swap, the
  checks and the load of the model. A drain that takes the full 15 minutes can leave too little time. The record lists
  these models. The deployment does not wait for another node to be available, and it is not blocked by this case.
* **The models of the node load again after the deployment.** The cordon lasts until the new container is checked, and the
  capacity planner places nothing on a cordoned node. The next node can start before the first one has its models back.
  Requests for a model that both nodes serve then wait for the load on the first node.
* **A deployment that changes nothing still cordons the node.** The manager only finds out that nothing changes when
  Compose does not recreate the container, which comes after the drain. A busy node can wait for its drain for nothing.
* **Nothing counts a request the orchestrator lost track of.** If the orchestrator keeps a request that never ended in
  its books, the node cannot drain, and the deployment ends as `drain_timeout`. The events show how many requests the
  orchestrator and the worker count.
* **A mix of nodes with and without the drain breaks the one-at-a-time rule** (see "Use"). A node without the drain does
  not wait for a node that still drains.
* **A deployment waits behind an earlier one of the same host.** The daemon takes deployments one at a time. A new
  deployment is not pulled while the earlier one waits for its turn or drains. `deploy --until-pulled` can then run out
  of time (exit code 12), and the deployment goes on. If the host gets two deployments in a row, it replaces the container
  twice.
* **A newer run can change the files of an older deployment.** Each run copies the compose file and the `.env` to the
  host. A deployment that still waits for its turn uses the files of the newer run when it replaces the container.
* **A failure after the job ended shows up in the next run.** The job is green when the image is pulled. The step "Show
  how the previous deployment ended" of the next run prints the events and the log of a failed container, and
  `node-manager status --logs` shows them on the host. The Logos admins also get a notification when the
  deployment ends (see "Reports").
* **The reports are one per node.** There is no notification for a whole rollout, and the orchestrator remembers the
  reports it accepted only in memory. After a restart of the orchestrator a repeated report would be sent again.
* **A drain figure is an estimate.** The status of the worker is a few seconds old, and a request that the orchestrator
  and the worker both count is counted once, so the figure is the larger of the two counts.
* **The version of the worker is not compared.** The check of the new worker is the new session and its first status. The
  image ID of the container already shows which image runs.

The removal of old images starts after the result is saved. `deploy --wait` can return a moment before it ends, and a
manager that stops in between leaves those images on the host. `docker rmi` removes them.
