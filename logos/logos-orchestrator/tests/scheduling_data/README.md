# SDI Tests (Queue, SDI Facades, Endpoints)

Run everything (unit + integration) with one command:
```bash
./run_scheduling_data_test.sh
```

What the runner does:
- Starts docker compose (logos-server) for parity/logs; continues locally if docker fails.
- Runs unit tests:
  - Queue: `tests/unit/queue/test_priority_queue_manager.py`
  - SDI facades: `tests/unit/sdi/`
  - Main/router glue: `tests/unit/main/`
  - Provider selection: `tests/unit/responses/`
- Runs SDI endpoint integration tests: `tests/integration/sdi/test_api_endpoints.py`

Scope covered:
- Queue priorities/enqueue/dequeue/peek/move/remove
- Azure SDI: rate-limit thresholds, status/capacity defaults
- Ollama SDI: loaded/VRAM from mocked /api/ps; queue state reflection
- Proxy vs resource routing, streaming vs non-streaming, sync vs async job flows
- Job submit/status auth and proxy/resource job processing

All tests are offline/mocked:
- No real DB/network; DBManager and provider polling are stubbed.
- Heavy deps (sentence_transformers, grpc/protobuf) are stubbed in `tests/conftest.py`.

Quick commands:
- Full SDI suite: `./run_scheduling_data_test.sh`
- Just unit layers: `pytest tests/unit/queue tests/unit/sdi tests/unit/main tests/unit/responses -v`
- Endpoint integrations: `pytest tests/integration/sdi/test_api_endpoints.py -v`
