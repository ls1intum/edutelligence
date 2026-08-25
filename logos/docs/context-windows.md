# Context windows

A model's context window on Logos is not a property of the model. It is a
property of the lane serving it: the capacity planner sizes a lane's KV cache
from the VRAM free on the node it lands on, and the window follows from that.
The same model can therefore run at 262,144 tokens on one worker and a fraction
of that on another, and a re-calibration moves it again without the model
changing.

That has one consequence that shapes everything below: **a single number cannot
be both safe and useful.** A request may be routed to any worker serving the
model, so the only window that always holds is the smallest one in the cluster
— and advertising that turns a 262k model into a 33k model for every client
that sizes its conversation from what it is told.

This document covers the four places that fact shows up.

## 1. What the API reports

`GET /v1/models` (and `/v1/models/{id}`) carry up to three figures per model.
Each is omitted when unknown, so cloud models and never-calibrated models keep
the object they had before these fields existed.

| Field                | Meaning                                                                    |
| -------------------- | -------------------------------------------------------------------------- |
| `max_model_len`      | Smallest window currently served anywhere. Safe whichever worker answers. The field vLLM itself uses, and the one a client should trust unconditionally. |
| `max_model_len_best` | Largest window currently served. Reachable because of the routing in §3.    |
| `max_context_length` | The model's own limit — what a lane serves once it gets all the KV cache it asks for. Known even while nothing is loaded, so it is the number to write into a config file that is read once at startup. |

The same three are exposed to the Spring webservice on
`GET /internal/model_context_windows` as `stats`, alongside the original flat
`windows` map (model → smallest window) that predates them. From there they
reach the UI as `context_window`, `context_window_best` and
`context_window_native` on `GET /me/keys/{id}/models`.

Source: `_served_context_window_stats()` in `logos/main.py`.

## 2. Placement floor — don't create a narrow lane at all

Since the narrowest lane defines what every client is told, the planner refuses
to create one below a configurable share of the model's own context length.
A node with room for a narrow lane but not a useful one defers instead.

| Variable                                | Default | Meaning                                                        |
| --------------------------------------- | ------- | -------------------------------------------------------------- |
| `LOGOS_MIN_CONTEXT_FRACTION`            | `0.5`   | Minimum share of the model's context length a lane must serve. `0` disables the floor (pre-existing behaviour), `1.0` is "full context or nothing". |
| `LOGOS_MIN_CONTEXT_FRACTION_OVERRIDES`  | —       | Per-model JSON override, e.g. `{"Qwen/Qwen3.8-27B": 1.0, "openai/gpt-oss-120b": 0.75}`. |

The floor is enforced in `_passes_minimum_load_feasibility`: a calibrated KV
point only counts as viable if the window it serves clears the floor. Two log
lines to look for when a model is not being placed:

```
Feasibility FAILED for <model>: smallest calibrated KV pair serving >=N context tokens needs …
Feasibility FAILED for <model>: no calibrated KV point serves the required minimum of N context tokens (widest is M)
```

The first is temporary — it clears when VRAM frees up. The second will not: no
calibrated point on that node reaches the floor at any KV size, so either lower
the fraction for that model or re-calibrate it.

A model whose context length is unknown is never blocked by the floor. It exists
to stop the planner *choosing* a narrow window, not to keep uncalibrated models
off the cluster.

## 3. Context-aware routing — send long requests where they fit

`_prefer_deployments_with_context_room` (`logos/main.py`) estimates what a
request needs and drops the workers that cannot serve it:

```
needed = prompt tokens + the reply the request reserved + 3000 tokens of margin
```

The 3000 is the same margin Claude Code keeps between its own hard stop and the
limit it was told; it absorbs the difference between the estimate and what the
worker's tokenizer really counts. The estimate itself (`logos/context_budget.py`)
counts characters and divides by 3, skipping base64 attachments, and rounds
against itself at every step — overestimating costs a roomier worker,
underestimating costs a 400.

Two deliberate escape hatches:

- **A worker whose window is unknown is always kept.** Cloud providers, Ollama
  lanes and lanes that have not reported yet have no window; that is missing
  information, not evidence of a narrow one.
- **When no worker fits, the widest ones are returned** rather than nothing. The
  request then fails upstream with the limit spelled out, exactly as before this
  filter existed, instead of turning into a 404 that names no model.

Audio uploads are left alone: a transcription hint is a few words and says
nothing about how much context the request needs.

## 4. Clients

### Claude Code — the `claude-logos` wrapper

`logos-ui/public/claude-logos.sh` (and `.ps1` for Windows) is served at
`<logos-url>/claude-logos.sh` and installed by the AI Tools page. It asks
`GET /v1/models` at every start, prints the window it got, and exports the
result into its own child process — nothing outside the wrapper is touched, so
plain `claude` keeps using an Anthropic subscription unchanged.

`LOGOS_CONTEXT_SOURCE` picks which figure to use: `available` (default,
`max_model_len_best`), `guaranteed` (`max_model_len`) or `max`
(`max_context_length`).

**The arithmetic matters, and it is not obvious.** Claude Code takes
`CLAUDE_CODE_MAX_CONTEXT_TOKENS`, subtracts `min(CLAUDE_CODE_MAX_OUTPUT_TOKENS,
20000)` from it, and auto-compacts 13,000 tokens below that. So:

```
compacts at  = window − headroom − min(max_output, 20000) − 13000
hard stop at = window − headroom − min(max_output, 20000) − 3000
```

Two things follow:

1. **Do not subtract the output reservation yourself.** Claude Code already
   does. Subtracting it again — which is what this wrapper and the AI Tools page
   used to do — throws away 20,000 tokens of context for nothing. On a
   111,200-token window that is the difference between compacting at 58,200 and
   at 37,240.
2. **`CLAUDE_CODE_MAX_OUTPUT_TOKENS` above 20,000 buys nothing.** The
   reservation is capped there regardless, so a larger value only inflates the
   `max_tokens` on the wire. The wrapper sets exactly 20,000.

The "auto-compact fires at ~60%" effect that started this work is these two
fixed deductions — 33,000 tokens in total — as a share of a window that was
already too small. It is not a percentage, and there is no knob to raise it:
`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` exists but is clamped by
`min(window × pct, window − 13000)`, so it can only compact *earlier*. The only
lever is the window itself, which is what §2 and §3 are for.

One caveat the wrapper warns about: a model id starting with `claude-` or
containing `[1m]` is resolved to one of Claude Code's own models, and
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` is ignored for it. `DISABLE_COMPACT=1` forces
the window through, at the cost of auto-compaction.

Useful commands:

```
claude-logos --logos-context     what window this session would get, no request made
claude-logos --logos-check       plus one real request against the gateway
claude-logos --logos-uninstall   remove the wrapper, its config and its key
```

### OpenCode

OpenCode reads its config once at startup and cannot re-read it, so the
generated `opencode.json` states `max_context_length` — the ceiling rather than
a number that goes stale. Long conversations may be turned down when capacity is
tight; the routing in §3 gives them the best available shot.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Claude Code compacts far earlier than the window suggests | The output reservation is being subtracted twice, or the session is running on `guaranteed` while `available` is much larger. Check `claude-logos --logos-context`. |
| `maximum context length is N tokens` 400s | The request landed on a worker narrower than the estimate expected. Switch that wrapper to `LOGOS_CONTEXT_SOURCE=guaranteed`. |
| A model is never placed on a node | The placement floor cannot be met there. Look for the "no calibrated KV point serves the required minimum" line and lower `LOGOS_MIN_CONTEXT_FRACTION` for that model. |
| `max_model_len` absent from `/v1/models` | No worker reports a window: a cloud model, or a vLLM lane running at the model's native maximum, which the worker does not report. |
