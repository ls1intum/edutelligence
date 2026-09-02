# Context windows

A model's context window on Logos is not a property of the model. It is a
property of the lane serving it: the capacity planner sizes a lane's KV cache
from the VRAM free on the node it lands on, and the window follows from that.
The same model can therefore be served at 262,144 tokens on one worker and a
fraction of that on another, and a re-calibration moves it again without the
model changing.

That has one consequence that shapes everything below: **a single number cannot
be both safe and useful.** A request may be routed to any deployment serving the
model, so the only window that always holds is the smallest one — and
advertising that turns a 262k model into a 33k model for every client that sizes
its conversation from what it is told.

This document covers the four places that fact shows up.

## 1. What the API reports

`GET /v1/models` (and `/v1/models/{id}`) carry up to four fields per model. Each
is omitted when unknown, so cloud models and never-calibrated models keep the
object they had before any of this existed.

| Field                       | Meaning                                                                    |
| --------------------------- | -------------------------------------------------------------------------- |
| `max_model_len_current_min` | Smallest window being served right now. Holds whichever deployment answers, so a client that never wants a rejected request sizes itself from this. |
| `max_model_len_current_max` | Largest window being served right now. Reachable because of the routing in §3. |
| `max_model_len_overall`     | The widest this model is ever served with — what a lane runs at once it gets all the KV cache it asks for. Independent of what is loaded at the moment, so it is known even for a model with no live lane, and it is the number to write into a config file that is only read at startup. The live snapshots only say this while a workernode is connected, so the number is topped up from the historic maximum Logos persists per model in `model_profiles` (`max_reported_context_length`, a high-water mark the profile upsert maintains): it is still known when **every** workernode is offline, and that — not a client-side guess — is what the claude-logos wrapper sizes a session from in that state. |
| `max_model_len`             | Repeats `max_model_len_current_min` under the name vLLM itself uses, so an OpenAI-compatible client that already reads that field keeps working. |

The same three are exposed to the Spring webservice on
`GET /internal/model_context_windows` as `stats` (`current_min`, `current_max`,
`overall`), alongside the original flat `windows` map (model → smallest window)
that predates them. From there they reach the UI as
`context_window_current_min`, `context_window_current_max` and
`context_window_overall` on `GET /me/keys/{id}/models`.

Source: `_served_context_window_stats()` in `logos/main.py`.

## 2. Placement floor — don't create a narrow lane at all

Since the narrowest lane defines what every client is told, a worker can refuse
to host a model below a share of its own context length. The floor is set **per
model in the worker's `config.yml`**, because the worker's hardware is what
decides which windows are reachable there:

```yaml
logos:
  capabilities_models:
    # Only worth serving at its full context — place it here or not at all.
    - model: Qwen/Qwen3.8-27B
      min_context_fraction: 1.0

    # Fine at anything from half its context up.
    - model: openai/gpt-oss-120b
      min_context_fraction: 0.5

    # No entry (or 0) = place at any width, the behaviour from before this field.
    - some-org/small-chat-model
```

The value travels with the model profile in the worker's runtime snapshot, so
the server picks it up without a restart of its own. It is enforced in two
places:

- `_passes_minimum_load_feasibility` — the planner does not *propose* a load
  that cannot reach the floor.
- `_select_kv_mb_max_model_len_pair` — the pair actually chosen at load time is
  constrained too, so a load path that bypasses the gate (contention,
  eviction-backed cold load, request-time cold load) cannot quietly place a
  below-floor lane either. When such a path has to place something anyway — a
  request is already waiting — it takes the **widest** fitting pair rather than
  the narrowest, and logs that it went below the floor.

Two log lines to look for when a model is not being placed:

```text
Feasibility FAILED for <model>: smallest calibrated KV pair serving >=N context tokens needs …
Feasibility FAILED for <model>: no calibrated KV point serves the required minimum of N context tokens (widest is M)
```

The first is temporary — it clears when VRAM frees up. The second will not: no
calibrated point on that node reaches the floor at any KV size, so either lower
`min_context_fraction` for that model or re-calibrate it.

A model whose context length is unknown is never blocked by the floor. It exists
to stop the planner *choosing* a narrow window, not to keep uncalibrated models
off the cluster.

## 3. Context-aware routing — send long requests where they fit

`_prefer_deployments_with_context_room` (`logos/main.py`) estimates what a
request needs and drops the deployments that cannot serve it:

```text
needed = prompt tokens + the output the request reserved + 3000 tokens of margin
```

**Where "the output the request reserved" comes from:** the request says so.
`max_tokens` (Anthropic Messages, chat completions), `max_completion_tokens` or
`max_output_tokens` (Responses API) — whichever is present. A request that names
none is assumed to reserve 20,000, because an uncapped request can generate
until it hits the window, and 20,000 is the largest default among the clients
Logos serves. This matters because vLLM charges input and output against one
budget: a prompt that fits on its own can still overflow once the reply it asked
for is reserved.

**Where the 3000 comes from:** it is the margin Claude Code keeps between its own
hard stop and the limit it was told. Using the same number means a session that
Claude Code considers safe is one this filter also considers safe. It absorbs the
difference between the estimate and what the worker's tokenizer really counts —
the estimate (`logos/context_budget.py`) counts characters and divides by 3,
skipping base64 attachments, and rounds against itself at every step, because
overestimating costs a roomier deployment while underestimating costs a 400.

The margin is part of `needed`, not something the lane has to hold in addition:
a lane serving 33,000 tokens is asked to fit `prompt + output + 3000 ≤ 33000`.
So a lane never has to "first make room" for the margin — it is simply expected
to have 3000 tokens more than the request strictly needs.

Two deliberate escape hatches:

- **A deployment whose window is unknown is always kept.** Cloud providers, and
  lanes that have not reported a window yet, have none; that is missing
  information, not evidence of a narrow window. It does mean
  `max_model_len_current_min` is only a promise across the deployments whose
  window is known — a request sized from it can still reach an unknown one.
- **When nothing fits, the widest deployments are returned** rather than
  nothing. The request then fails upstream with the limit spelled out, exactly
  as before this filter existed, instead of turning into a 404 that names no
  model.

Audio uploads are left alone: a transcription hint is a few words and says
nothing about how much context the request needs.

## 4. Clients

### Claude Code — the `claude-logos` wrapper

`logos-ui/public/claude-logos.sh` (and `.ps1` for Windows) is served at
`<logos-url>/claude-logos.sh` and installed by the AI Tools page. At every start
it asks `GET /v1/models`, prints the window it got, and exports the result into
its own child process — nothing outside the wrapper is touched, so plain
`claude` keeps using an Anthropic subscription unchanged.

It also does two things with the listing it already has in hand:

- **Warms the model up.** `POST /v1/models/{model}/warmup` tells the planner the
  model is about to be used and returns immediately. It records the same latent
  demand the scheduler records when classification prefers a model it did not
  get, and wakes the planner cycle early — so the cold load can overlap with the
  seconds a developer spends reading the startup line. It is a hint, not a
  reservation: the planner still decides using its own fairness rules, a warmup
  can never evict a lane real traffic is using, and no inference request is ever
  sent on the caller's behalf. Warming a model the key has no access to is a 404.
- **Names models that are new to you.** The id list is compared against the one
  from the last run (`~/.config/claude-logos/known-models`); additions are
  printed. The first run records the baseline silently rather than announcing
  everything as new.

`LOGOS_CONTEXT_SOURCE` picks which figure to size the session from: `available`
(default, `max_model_len_current_max`), `guaranteed`
(`max_model_len_current_min`) or `max` (`max_model_len_overall`).

**The arithmetic matters, and it is not obvious.** Claude Code takes
`CLAUDE_CODE_MAX_CONTEXT_TOKENS`, subtracts `min(CLAUDE_CODE_MAX_OUTPUT_TOKENS,
20000)` from it, and auto-compacts 13,000 tokens below that. So:

```text
compacts at  = window − headroom − min(max_output, 20000) − 13000
hard stop at = window − headroom − min(max_output, 20000) − 3000
```

Two things follow:

1. **Do not subtract the output reservation yourself.** Claude Code already
   does. Subtracting it again — which is what this wrapper and the AI Tools page
   used to do — throws away 20,000 tokens of context for nothing. On a
   111,200-token window, the old wrapper (which also reserved 32,768 for output
   and took 8,192 of headroom) compacted at 37,240 tokens; the same window now
   compacts at 75,976.
2. **`CLAUDE_CODE_MAX_OUTPUT_TOKENS` above 20,000 buys nothing.** The
   reservation is capped there regardless, so a larger value only inflates the
   `max_tokens` on the wire. The wrapper sets exactly 20,000.

**What happens when a session hits the limit?** In order: at
`window − reserve − 13000` Claude Code compacts the conversation by itself and
carries on. If a single turn grows past `window − reserve − 3000` it refuses to
send and asks for a `/compact` instead. Neither is an error the user has to
recover from — the failure mode this replaces was a 400 from vLLM mid-turn.

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

```bash
claude-logos --check       connection, model and how much room a session would get
claude-logos --update      replace the wrapper with the current one
claude-logos --uninstall   remove the wrapper, its config and its key
claude-logos --help        this, then claude's own help
```

#### Revisions

`CLAUDE_LOGOS_VERSION` near the top of the script is a monotonic integer — bump it
in the same commit as any change installed copies should pick up, and keep the
`$ClaudeLogosVersion` in `claude-logos.ps1` in step. It is the only place the
revision lives: Logos serves the current wrapper at the same URL an installed copy
came from, so there is no second file to keep in sync and no way for the two to
disagree.

Installed copies **never update themselves.** At most once a day the wrapper
fetches that URL in the background and records the revision it found; the next
start compares it and, if a newer one exists, prints the one command that replaces
it. So the notice costs no startup time and appears one start after a release —
soon enough for something the user then has to type anyway.

`--update` replaces the script and nothing else. The key, config and settings
layer stay as they are, so an update is not a re-setup and the AI Tools page does
not have to be visited again. It validates before replacing: the download has to
contain a revision line and has to parse, because otherwise a captive portal or a
proxy error page would leave a working wrapper overwritten with HTML — and that
file is the next thing the user runs. The replacement is a rename within one
directory, so a still-running copy keeps reading the old inode and finishes
normally.

### OpenCode

OpenCode reads its config once at startup and cannot re-read it, so the
generated `opencode.json` states `max_model_len_overall` — the ceiling rather
than a number that goes stale. Long conversations may be turned down when
capacity is tight; the routing in §3 gives them the best available shot.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Claude Code compacts far earlier than the window suggests | The output reservation is being subtracted twice, or the session is running on `guaranteed` while `available` is much larger. Check `claude-logos --check`. |
| `maximum context length is N tokens` 400s | The request landed on a deployment narrower than the estimate expected — most likely one that reports no window. Switch that wrapper to `LOGOS_CONTEXT_SOURCE=guaranteed`. |
| A model is never placed on a node | The placement floor cannot be met there. Look for the "no calibrated KV point serves the required minimum" line and lower `min_context_fraction` for that model in the worker's config.yml. |
| `max_model_len` absent from `/v1/models` | Nothing reports a window that always holds: a cloud model, a vLLM lane running at the model's native maximum (which the worker does not report), or every workernode offline. In the last case `max_model_len_overall` still carries the model's historic maximum, and the claude-logos wrapper sizes the session from it (startup line says "no lane is up yet"). |
