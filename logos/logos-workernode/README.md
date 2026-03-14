# LogosWorkerNode

LogosWorkerNode is the outbound worker for local inference in Logos.

It does three things:
- starts one lane process per configured model,
- keeps a websocket session open to Logos,
- reports runtime/device/lane status so Logos can schedule against warm/cold capacity.

## What changed
- Provider type is `logosnode`.
- The worker is lane-only. There is no singleton Ollama runtime API anymore.
- Local admin HTTP is private/operator-facing only.
- Benchmarks and research material live under `tools/` and `research/`.

## Local dev
1. Edit [config.yml](/Users/kubaj/edutelligence/logos/logos-workernode/config.yml).
2. Copy `.env.example` to `.env` if you need build overrides.
3. Start the worker:
```bash
./start.sh
```
4. Check health:
```bash
curl http://localhost:8444/health
```

## GPU worker
Use the GPU compose overlay when the host exposes NVIDIA runtime support:
```bash
./start.sh --gpu
```

## Docs
- Setup: [QUICKSTART.md](/Users/kubaj/edutelligence/logos/logos-workernode/QUICKSTART.md)
- Lane operations: [LANES.md](/Users/kubaj/edutelligence/logos/logos-workernode/LANES.md)
- Validation and test commands: [TESTING.md](/Users/kubaj/edutelligence/logos/logos-workernode/TESTING.md)
- Benchmark scripts and API collections: `tools/`
- Research notes and benchmark outputs: `research/`
