---
title: Local Development
---

# Local development

All blocks below start from the repository root (`edutelligence/`) and
re-establish their own working directory, so they can be run in any order
from a fresh checkout.

## Development stack

```bash
cd logos
docker compose -f docker-compose.dev.yaml up --build
```

The compose stack serves the API (Traefik at `http://localhost:18081`) but
not the web UI. Start the Angular dev server on the host as well (see the
Angular UI block below), then open `http://localhost:4200/`.

## Orchestrator (Python)

The orchestrator is the main Python service, an installable package under
`logos-orchestrator/`. Use Python 3.13 and `uv`:

```bash
cd logos/logos-orchestrator
# The orchestrator depends on the repository-root `shared` package; CI links
# it in before installing, so do the same:
ln -s ../../shared shared
uv venv .venv --python 3.13
source .venv/bin/activate
uv pip install .
```

## Angular UI

The UI can be developed independently:

```bash
cd logos/logos-ui
npm ci
npm start
```

## Pre-commit hooks

Run the Logos pre-commit hooks before submitting changes:

```bash
pre-commit run --config logos/.pre-commit-config.yaml --all-files
```
