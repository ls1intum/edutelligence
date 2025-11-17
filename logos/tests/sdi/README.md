# SDI Tests

Tests for the Scheduling Data Interface (SDI) providers.

## Quick Start

Run all SDI tests in Docker with a single command:

```bash
./tests/sdi/test_sdi.sh
```

This script will:
- ✅ Start Docker containers automatically
- ✅ Wait for services to be ready
- ✅ Run all 8 SDI tests
- ✅ Show colored output with clear success/failure indicators

## Running with Real Ollama (Optional)

To enable the real Ollama integration test, install Ollama on your machine:

1. **Download Ollama**: https://ollama.com
2. **Start Ollama**: `ollama serve`
3. **Pull a model**: `ollama pull llama2:7b`

The test script will automatically detect Ollama running on your Mac and run the integration test. If Ollama is not running, that test will be skipped (7/8 tests will still pass).

## What Gets Tested

All tests use mocked data except the optional Ollama integration test:

- ✅ `test_ollama_provider_with_mock` - VRAM tracking and model loading
- ✅ `test_ollama_provider_unloaded_model` - Cold start prediction
- ✅ `test_ollama_provider_expired_model` - Expiry detection
- ✅ `test_azure_provider` - Rate limit tracking
- ✅ `test_azure_provider_low_quota` - Low quota detection
- ✅ `test_azure_provider_multiple_deployments` - Per-deployment rate limits
- ✅ `test_ollama_queue_tracking` - Queue depth management
- ⚪ `test_ollama_provider_real` - Real Ollama integration (requires Ollama)

## Manual Test Execution

If you need to run tests manually:

### Inside Docker container:
```bash
docker compose exec logos-server poetry run pytest logos/tests/sdi/test_sdi.py -v
```

### Run a specific test:
```bash
docker compose exec logos-server poetry run pytest logos/tests/sdi/test_sdi.py::test_azure_provider -v
```

### With detailed output:
```bash
docker compose exec logos-server poetry run pytest logos/tests/sdi/test_sdi.py -vv -s
```
