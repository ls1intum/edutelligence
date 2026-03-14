# Testing

Focused worker tests:
```bash
PYTHONPATH=../src:. pytest -q \
  tests/test_logos_bridge.py \
  tests/test_lane_models.py \
  tests/test_lane_manager.py \
  tests/test_vllm_process.py
```

Focused Logos integration tests:
```bash
PYTHONPATH=../src:. pytest -q \
  ../tests/unit/main/test_node_controller_integration.py \
  ../tests/unit/sdi/test_ollama_facade.py
```

Benchmark and research utilities were moved out of the runtime root:
- scripts and collections: `tools/`
- result sets and writeups: `research/`
