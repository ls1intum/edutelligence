# SDI Tests

Tests for the Scheduling Data Interface (SDI) providers.

## Running Tests

**No Docker needed** - All tests use mocked data and run in-memory.

### Run all SDI tests:
```bash
poetry run pytest tests/sdi/test_sdi.py -v
```

### Run a specific test:
```bash
poetry run pytest tests/sdi/test_sdi.py::test_ollama_provider_with_mock -v
```

### Run with detailed output:
```bash
poetry run pytest tests/sdi/test_sdi.py -vv -s
```

## Test Coverage

- `test_ollama_provider_with_mock` - OllamaDataProvider with mocked /api/ps
- `test_ollama_provider_unloaded_model` - Cold start prediction for unloaded models
- `test_ollama_provider_expired_model` - Expiry detection from cached data
- `test_azure_provider` - AzureDataProvider with rate limit headers
- `test_azure_provider_low_quota` - Low quota detection
- `test_ollama_queue_tracking` - Queue depth management
- `test_ollama_provider_real` - Real Ollama instance (skipped if not running)

## Real Ollama Test

The `test_ollama_provider_real` test connects to a real Ollama instance at `http://127.0.0.1:11434`.

To enable this test:
1. Install Ollama: https://ollama.com
2. Start Ollama: `ollama serve`
3. Pull a model: `ollama pull llama2:7b`

The test will automatically skip if Ollama is not running.
