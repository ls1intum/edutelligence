# Testing

## Worker node tests

```bash
cd logos-workernode
PYTHONPATH=../src:. pytest -q \
  tests/test_logos_bridge.py \
  tests/test_lane_models.py \
  tests/test_lane_manager.py \
  tests/test_vllm_process.py \
  tests/test_model_profiles.py
```

## Logos integration tests

```bash
cd logos
PYTHONPATH=src pytest -q \
  tests/unit/main/test_node_controller_integration.py \
  tests/unit/sdi/test_ollama_facade.py \
  tests/unit/sdi/test_scheduler_view.py
```

## Scheduling & capacity tests

```bash
cd logos
PYTHONPATH=src pytest -q \
  tests/unit/pipeline/test_ettft_estimator.py \
  tests/unit/pipeline/test_correcting_scheduler.py \
  tests/unit/capacity/
```

## All Logos unit tests

```bash
cd logos
PYTHONPATH=src pytest tests/unit/ -v
```

## Notes
- Benchmark and research utilities live under `tools/` and `research/`.
- The pre-existing `test_route_and_execute_proxy_branch` failure is unrelated to scheduling changes.
