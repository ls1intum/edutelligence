# AGENTS.md - logos-node-manager

Logos-node-manager handling GPU worker node redeployments. The `max-parallel: 1` set in the `logos_deploy-dev.yml` and `logos_deploy-prod.yml` files in `../../.github/workflows` serializes hosts, so there are other GPU worker nodes that the orchestrator can route to, when a node is deploying a new version.

Sources of truth:
- `README.md`

If the code does not align with what is written in `README.md`, check if there is a test pinning the code behaviour, if so, the `README.md` is stale. Update it in the same change with the correct behaviour. If no test exists, or you suspect the code mismatch is a bug, report it, and ask how to proceed.

## Notes to agents

- Do not flip the `node-manager` flag in the `logos_deploy-dev.yml` and `logos_deploy-prod.yml` files by yourself.
- You are NOT allowed to dispatch deploys or touch real hosts.
- Every step must be safe to repeat, because a restart can re-enter any phase.
- ALWAYS save the record before an irreversible action.
- Only clean up, if the record is finished.

## Tests

Tests are found in the `tests` folder. A special test is run by using real Docker, it needs a running Docker engine, the compose plugin, and a network connection. To run it, run the `run-smoke.sh` in `tests/smoke/`. The tests are safe to run, `tests/smoke/run-smoke.sh` creates and deletes only `nm-smoke*` things, and `KEEP=1` leaves them behind, they are not deleted automatically.
