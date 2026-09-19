# AGENTS.md — Logos Guide for AI Agents

**Logos** is an LLM Engineering Platform: an intelligent proxy between LLM consumers and multiple LLM providers (self-hosted GPU workers, Azure, OpenAI), with usage logging, billing, central resource management, policy-based model selection, scheduling, GPU capacity planning, and monitoring.

`logos/` is a multi-service directory, not a single project.

## Components

| Directory | Stack | Role |
|-----------|-------|------|
| `logos-orchestrator/` | Python 3.13, FastAPI, `uv` | Core proxy: auth, classification, scheduling, provider routing, request logging. See its own `AGENTS.md`. |
| `logos-webservice/` | Java 25, Spring Boot, Maven | Admin/management REST API **and** public inference gateway (`/v1`, `/openai`, `/jobs`). **Owns the Postgres schema** via Liquibase. See its own `AGENTS.md`. |
| `logos-ui/` | Angular 22, npm | Web application for teams, keys, models, stats. See its own `AGENTS.md`. |
| `logos-workernode/` | Python | GPU worker-node control plane: vLLM lane lifecycle, calibration, websocket bridge to the orchestrator. See its own `AGENTS.md`. |
| `logos-agent/` | Python, FastAPI | Runs coding agents in isolated containers on spare serving capacity. See its own `AGENTS.md` and `README.md`. |
| `e2e/` | pytest, Playwright | GPU-less end-to-end suite. See its own `AGENTS.md` and `README.md`. |
| `agent-gateway/`, `rate-limit-gateway/` | nginx | Edge proxies around the agent runner and the orchestrator. |
| `keycloak/` | — | Dev realm seed (`tum-realm.json`); all seeded dev users have password `password`. |
| `db/` | — | Plain `postgres:17` + pg_cron Dockerfile — **no schema here**. |
| `docs/` | Docusaurus | User/admin/developer documentation site. Role-guide screenshot refresh + demo seed: see `docs/AGENTS.md`. |
| `benchmarks/` | Python | Scheduler/throughput benchmarking scripts. |

## Cross-Cutting Rules (Not Inferable From the Code)

### Schema ownership

The Postgres schema is owned by `logos-webservice` and migrated via Liquibase changelogs in `logos-webservice/src/main/resources/liquibase/changelog/`. A changelog is only applied if it is `<include>`-ed in `master.xml` — a file left out is silently never run. The orchestrator and agent only read/write tables (raw SQL, no migrations); `db/` has no `init.sql`.

### Entity hierarchy

```text
User (role: app_developer | app_admin | logos_admin)
  └── Team(s), via team_members (is_owner flag)
        └── API Key(s) (key_type: developer | application | service)
              └── Model/Provider access:
                    use_custom_permissions=true  → key's own api_key_*_permissions
                    use_custom_permissions=false → team's team_*_permissions (default)
```

The older Process/Profile hierarchy (`process`, `profiles`, `profile_model_permissions`, `model_api_keys` tables) **no longer exists** — never design against it.

### Git workflow (MANDATORY, CI-enforced)

- **PR title** must match: `` ^`(Development|General|Athena|Atlas|AtlasML|Iris|Logos|Memiris)`:\s[A-Z].*$ `` — e.g. `` `Logos`: Add team management endpoints ``.
- **Commit messages**: `Logos: Description starting with capital letter (#issue_number)`.
- **Branch names**: `feature/logos/description` or `logos/description`.
- Never merge to `main` without a PR. After opening a PR, check `gh pr checks` and fix failures immediately.
- **Every PR that changes the UI must include full-page desktop AND mobile screenshots** in the PR description (never committed to the repo). The exact capture/hosting procedure is the `ui-screenshots` skill (see below).
- **Every PR that changes how a documented page looks** must also refresh the matching committed role-guide PNGs under `docs/static/img/roles/` in that same PR (layout, chrome, empty/error states, sidebar — anything a reader would notice). Follow `docs/AGENTS.md` (seed + shot matrix).

### Conventions

- Avoid the imprecise terms `frontend` and `backend` in comments and documentation — name the actual component (user interface, web application, application server, feature service, data service, infrastructure service).
- Keep comments focused on current behavior and implementation constraints; no issue/PR history or local provider names.
- Pre-commit hooks (autoflake, isort, black 120 cols, flake8) gate Python code — see `logos/README.md` for setup and manual runs.

### Shared sibling

The `shared/` directory at the repo root (sibling of `logos/`) is symlinked into the orchestrator for local dev/CI: `ln -s ../../shared logos/logos-orchestrator/shared` (note the extra `../`).

### Running the full stack

```bash
docker compose -f docker-compose.dev.yaml up --build   # from logos/
cd logos-ui && ng serve                                 # web application on :4200
```

Log in with a seeded Keycloak user (e.g. `tobias.wasner` / `password` — logos admin). See `README.md` for roles and team provisioning.

## Skills

Task-specific playbooks live in `.agents/skills/<name>/SKILL.md`, in the [Agent Skills](https://agentskills.io) format, and are mirrored by a frontmatter-only stub under `.claude/skills/<name>/` because clients scan different directories. Before adding, renaming or removing one, read [`.agents/skills/AGENTS.md`](.agents/skills/AGENTS.md) — it has the mirroring rules. An agent that discovers neither location can read the file directly.

| Skill | Use it for |
|-------|------------|
| [`ui-screenshots`](.agents/skills/ui-screenshots/SKILL.md) | Full-page desktop + mobile screenshots of the web application for PRs and documentation. |
| [`docs/AGENTS.md`](docs/AGENTS.md) | Role-guide PNG refresh under `docs/static/img/roles/` (committed), including the `docs/seed/role-screenshots.sql` priming recipe. |
