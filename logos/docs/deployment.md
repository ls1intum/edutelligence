# Logos deployment environments

Logos images are built by the `Logos - Build` workflow and pushed to the Harbor
registry (`${LOGOS_HARBOR_REGISTRY}/logos`). PR builds are tagged `pr-<number>`,
builds on `main` are tagged `latest`.

The vLLM worker image is always built on the first run of a PR (and when a PR is
reopened), which guarantees that its `pr-<number>` tag exists before a dev
deployment. On later PR updates, the workflow reuses that tag unless files in
the worker runtime (`logos_worker_node`), its copied tools, dependency list,
Dockerfile/build-context rules, or its build workflow changed since the last
successful worker build in that PR. Worker documentation, tests, research
results, Compose files, and host configuration do not trigger an image rebuild.
Pushes to `main` and releases continue to rebuild the worker image.

| Environment | Workflow | Trigger | Nodes (GitHub environments) |
|---|---|---|---|
| Prod | `Logos - Deploy to Prod` | auto after `Logos - Build` on `main`, or manual | `Logos - Prod`, `Logos Worker - Prod - deioma` |
| Test | `Logos - Deploy to Test` | manual (`workflow_dispatch`, image-tag input) | `Logos - Test`, `Logos Worker - Prod - deimama`, `Logos Worker - Prod - deipapa` |
| Dev | `Logos - Deploy to Dev` | manual (`workflow_dispatch`, image-tag input) | `Logos - Dev`, `Logos Worker - Test - hochbruegge` |

Each deploy job copies the docker compose file and a generated `.env` (all
environment vars/secrets except the SSH/registry plumbing) to the node and runs
`docker compose up -d` there. Core nodes use `logos/docker-compose.yaml` under
`/opt/logos`; worker nodes use `logos/logos-workernode/docker-compose.yml` under
`/opt/logos-workernode`.

## Required configuration per GitHub environment

Repository-level (already configured): `LOGOS_HARBOR_REGISTRY`,
`LOGOS_HARBOR_USER` (vars), `LOGOS_HARBOR_PASSWORD` (secret), and the
`DEPLOYMENT_GATEWAY_*` vars/secrets inherited from the organization.

### Core node (e.g. `Logos - Dev`)

Variables:

- `VM_HOST`, `VM_USERNAME` — target VM and SSH user
- `LOGOS_DOMAIN`, `LOGOS_CERT_RESOLVER`, `LOGOS_CORS_ALLOWED_ORIGINS`, `ACME_EMAIL`
- `KEYCLOAK_ADMIN_BASE_URL`, `KEYCLOAK_AUDIENCE`, `KEYCLOAK_CLIENT_ID`,
  `KEYCLOAK_ISSUER_URI`, `KEYCLOAK_JWKS_URI`, `KEYCLOAK_ROLES_APP_ADMIN`,
  `KEYCLOAK_ROLES_LOGOS_ADMIN`, `KEYCLOAK_SYNC_CLIENT_ID`,
  `KEYCLOAK_SYNC_ENABLED`, `KEYCLOAK_TEAM_ROLE_SUFFIXES`

Secrets:

- `VM_SSH_PRIVATE_KEY`
- `LOGOS_INTERNAL_SECRET`
- `KEYCLOAK_SYNC_CLIENT_SECRET`
- `PROMETHEUS_API_KEY`

### Worker node (e.g. `Logos Worker - Test - hochbruegge`)

Variables:

- `VM_HOST`, `VM_USERNAME` — target GPU node and SSH user
- `LOGOS_URL` — URL of the core node's orchestrator this worker registers with
- `LOGOS_TMPFS_CACHE_PATH`, `TMPFS_SIZE`, `OLLAMA_MODELS_MOUNT`

Secrets:

- `VM_SSH_PRIVATE_KEY`
- `LOGOS_API_KEY` — key the worker uses to authenticate against the orchestrator
- `HF_TOKEN`
