---
title: Local Development
---

# Local development

Run the development stack from `logos/`:

```bash
docker compose -f docker-compose.dev.yaml up --build
```

For the orchestrator (the main Python service, an installable package under
`logos-orchestrator/`), use Python 3.13 and `uv`:

```bash
cd logos-orchestrator
uv venv .venv --python 3.13
source .venv/bin/activate
uv pip install .
```

The Angular UI can be developed independently:

```bash
cd logos-ui
npm ci
npm start
```

Run the Logos pre-commit hooks before submitting changes:

```bash
pre-commit run --config logos/.pre-commit-config.yaml --all-files
```
