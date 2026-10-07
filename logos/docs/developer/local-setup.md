---
title: Local Development
---

# Local development

All blocks below start from the repository root (`edutelligence/`). Each block
sets its own working directory. You can run the blocks in any order from a
new checkout.

## Development stack

```bash
cd logos
docker compose -f docker-compose.dev.yaml up --build
```

The compose stack serves the API (Traefik at `http://localhost:18081`). It
does not serve the web UI. Also start the Angular dev server on the host (see
the Angular UI block below). Then open `http://localhost:4200/`.

## Orchestrator (Python)

The orchestrator is the main Python service. It is an installable package in
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

You can develop the UI separately:

```bash
cd logos/logos-ui
npm ci
npm start
```

## Pre-commit hooks

Before you submit changes, run the Logos pre-commit hooks:

```bash
pre-commit run --config logos/.pre-commit-config.yaml --all-files
```
