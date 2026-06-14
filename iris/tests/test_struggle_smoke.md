# Struggle-Intervention Pipeline — Manual Smoke Runbook

This is a **manual** end-to-end smoke test (not an automated pytest). It exercises the
full `struggle_intervention_pipeline` in isolation: route → background worker → agent
loop → `post_agent_hook` → `StruggleInterventionCallback` POST. Run it once locally with
a real chat-role LLM configured, capture the callback body, and paste the observed body
into the section at the bottom so Plan 2 (Artemis) can assert against the real shape.

## Prerequisites

- A local Pyris able to resolve at least one **chat**-role LLM for
  `struggle_intervention_pipeline` (the LLM config block was added in
  `application.example.yml`; point `APPLICATION_YML_PATH` at a local config that defines
  the referenced models, e.g. `gpt-oss` / `oai-gpt-5-mini`).
- The Pyris internal API token (the `Authorization: Bearer <token>` the server expects).

## Step 1 — start Pyris locally

Follow the repo's standard local run (see `README.md` / `CONTRIBUTING.md`; do not invent a
command). Confirm the server is up on its usual port (assumed `http://localhost:8000`
below) and that `GET /api/v1/health` (or the documented health route) responds.

## Step 2 — start a callback sink

`on_status_update()` treats any non-2xx callback POST as a failure, so the sink must return
200 and print the body. Create `scratch_sink.py`:

```python
from http.server import BaseHTTPRequestHandler, HTTPServer


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        print(f"\n=== CALLBACK {self.path} ===\n{self.rfile.read(n).decode()}\n")
        self.send_response(200)
        self.end_headers()


HTTPServer(("127.0.0.1", 9099), H).serve_forever()
```

Run it (leave running): `python scratch_sink.py`. It 200s every POST and prints the JSON.

## Step 3 — fire a request

`artemisBaseUrl` points at the sink so the callback lands there.

```bash
curl -i -X POST http://localhost:8000/api/v1/pipelines/struggle-intervention/run \
  -H "Authorization: Bearer <pyris-api-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "settings": {"authenticationToken":"smoke-1","selection":"CLOUD_AI","artemisBaseUrl":"http://localhost:9099","variant":"default"},
    "initialStages": [],
    "struggleSignal": {"alert":{"tSessionS":540,"primaryBoundary":"FM","boundaryTypes":["FM"],"severity":0.72,"path":"armed","inWarmup":false,"inGrace":false},"trajectory":[{"t":520,"s":0.5,"v":0.6},{"t":530,"s":0.6,"v":0.7}],"dominantComponents":[{"name":"feedbackViewing","value":0.8}],"sessionSeconds":540},
    "programmingExercise": {"id":1,"title":"T","problemStatement":"Return the sum of a list.","programmingLanguage":"JAVA"},
    "programmingExerciseSubmission": {"id":1,"isPractice":false,"repository":{"src/Sum.java":"class Sum { int sum(int[] a){ return 0; } }"},"buildFailed":true,"buildLogEntries":[],"latestResult":null},
    "chatHistory": []
  }'
```

## Step 4 — expected result

- The HTTP response to the curl is **`202 Accepted`** (the route is fire-and-forget).
- Within a few seconds the sink receives a POST to
  `/api/iris/internal/pipelines/struggle-intervention/runs/smoke-1/status` whose JSON has
  the **flat top-level** fields:
  - `action` ∈ {`silent`, `ambient`, `active`}
  - `confidence` (number, 0.0-1.0)
  - `result` (the hint string; present when `action != silent`, `null` for `silent`)
  - alongside the usual `stages` / `tokens`.
- A **second, trailing** callback for the same run is expected, with `result` and
  `confidence` set back to `null` but `action` still set. This is the known
  `AbstractAgentPipeline` double-`done()` behavior (see the Task 5 trailing-callback note);
  Artemis (Plan 2) is idempotent per `run_id` and ignores the trailing one.

Confirm the body matches `StruggleInterventionStatusUpdateDTO`
(`iris/src/iris/domain/status/struggle_intervention_status_update_dto.py`):
`action`, `result`, `confidence`, `rationale` at the top level.

## Observed callback body (fill in after running — for Plan 2 to assert against)

```json
<paste the first authoritative callback body here>
```

```json
<paste the trailing callback body here>
```
