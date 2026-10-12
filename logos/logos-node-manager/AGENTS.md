# AGENTS.md - logos-node-manager

Logos-node-manager handling GPU worker node redeployments. Deployments run one after another which is set by `max parallel: 1` set in the logos-deploy-`<server-name>`.yaml files in `../../.github/workflows`.

Sources of truth:
- `README.md`

If any historical note conflicts with runtime behavior, follow the code and the docs above.

## Notes to agents

- Do not flip the `node-manager` flag in the logos-deploy-`<server-name>`.yaml does not matter if it is currently en- or disabled. You are NOT allowed to dispatch deploys, and touch real hosts.
- every step must be safe to repeat, because a restart can re-enter any phase.
- ALWAYS save the recors, before an irreversible action.
- only clean up, if the record is finished.
- the NODE_MANAGER_* names must match the compose service and .env.example

## Tests

Tests are found in the `/test` folder. A special test is run by using a fake Docker. To run it run the `run-smoke.sh in` in `/tests/smoke/`. Both tests are safe to run, `tests/smoke/run-smoke.sh` creates and deltes only `nm-smoke*` things, and `KEEP=1` keeps them behind, they are not deleted automtically.
