# LogosWorkerNode

LogosWorkerNode is the outbound worker for local inference in Logos.

It does four things:
- starts one lane process per configured model,
- keeps a websocket session open to Logos,
- reports runtime/device/lane status so Logos can schedule against warm/cold capacity,
- auto-calibrates model memory profiles (observed reservation, base residency, sleeping residual) and persists them across restarts.

## Configuration split

| Source | What | Managed by |
|---|---|---|
| `.env` | Credentials (`LOGOS_URL`, `LOGOS_API_KEY`) | GitHub secrets/variables |
| `config.yml` | Hardware & tuning (capabilities, vLLM overrides, engine settings) | Ansible |
| `/app/data/` | Runtime state (lanes, model profiles) | Auto-managed (Docker volume) |

No overlap. Credentials never go in `config.yml`. Hardware config never goes in `.env`.

## Local dev
1. Copy `.env.example` to `.env` and fill in connection credentials.
2. Edit `config.yml` for capabilities and engine settings.
3. Start the worker:
```bash
docker compose -f docker-compose.dev.yml up --build
```
4. Check health:
```bash
curl http://localhost:8444/health
```

## GPU worker
Use the production compose file when the host exposes NVIDIA runtime support:
```bash
docker compose up -d
```

vLLM requirement:
- vLLM lanes require a working `nvidia-smi`.
- LogosWorkerNode blocks vLLM startup when `nvidia-smi` is unavailable or misconfigured.
- If you want to run without `nvidia-smi`, use Ollama lanes only.

## Docs
- Setup: [QUICKSTART.md](QUICKSTART.md)
- Lane operations: [LANES.md](LANES.md)
- Validation and test commands: [TESTING.md](TESTING.md)
- Benchmark scripts and API collections: `tools/`
- Research notes and benchmark outputs: `research/`
