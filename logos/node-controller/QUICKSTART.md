# Node Controller Quickstart

## 1. Start

```bash
cd /home/ge84ciq/node-controller-test/edutelligence/logos/node-controller
./start.sh
```

If Docker permissions fail, run:

```bash
sudo ./start.sh
```

`start.sh` first-run defaults:
- creates `.env` from `.env.example`,
- builds image with bundled `ollama` and `vllm`,
- starts controller on `http://127.0.0.1:8444`.

## 2. Verify

```bash
curl -s http://127.0.0.1:8444/health | jq .
```

Set auth variables for admin endpoints:

```bash
export CTRL=http://127.0.0.1:8444
export API_KEY=RANDOM_DEFAULT_KEY
```

Confirm lane admin API:

```bash
curl -s -H "Authorization: Bearer $API_KEY" "$CTRL/admin/lanes/templates" | jq .
```

## 3. Apply your first lane

Clear everything:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"lanes":[]}' \
  "$CTRL/admin/lanes/apply" | jq .
```

Then apply either an Ollama lane or a vLLM lane from `LANES.md`.

## Notes

- Default model storage is Docker volume `ollama-models`.
- To reuse host model files, set `OLLAMA_MODELS_MOUNT` in `.env` and rerun `./start.sh`.
