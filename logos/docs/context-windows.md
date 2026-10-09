# Context windows

The context window of a model on Logos is not a property of the model. It is a property of the lane that serves the model. The capacity planner sizes the KV cache of a lane from the free VRAM on the node where the lane starts. The window follows from the KV cache size. The same model can have 262,144 tokens on one worker and a fraction of that on another worker. A re-calibration can also change the window while the model stays the same.

This has one result that shapes the rest of this page: **a single number cannot be both safe and useful.** Logos can route a request to any deployment that serves the model. Only the smallest window is always valid. If Logos advertises the smallest window, a 262k model becomes a 33k model for each client that sizes its conversation from the advertised value.

This page describes the four places where this fact has an effect.

## 1. What the API reports

`GET /v1/models` (and `/v1/models/{id}`) return up to four fields for each model. Logos omits a field when the value is unknown. A model with no known window keeps the same object as before. Logos combines these sources in this order:

1. The workernode runtime snapshots. They show what the workers serve now.
2. The windows that a cloud upstream publishes on its own `/v1/models`. These values are measured.
3. The historic maximum that the database keeps for each model.
4. The input context window that the upstream registry publishes for the model. Logos uses this source only for a model that no measured source knows. The Azure family is the main example.

The webservice refreshes `model_capabilities` from the registry once a day. The orchestrator uses the registry value only for models that no other source reports. Thus the registry value never makes a measured window wider. The orchestrator also uses it only for models that have an associated cloud provider. A cloud upstream serves a catalog model at its published size. The window of a local model is a property of the calibrated lane. Thus Logos must not report the registry value for a local-only model that has no lane running.

| Field                       | Meaning                                                                    |
| --------------------------- | -------------------------------------------------------------------------- |
| `max_model_len_current_min` | The smallest window that Logos serves now. It is valid for each deployment that can answer. A client that must never get a rejected request sizes itself from this value. |
| `max_model_len_current_max` | The largest window that Logos serves now. A request can reach it because of the routing in §3. |
| `max_model_len_overall`     | The widest window that Logos ever serves for this model. It is the window of a lane that gets all the KV cache it asks for. It does not depend on what is loaded now. Thus it is known for a model that has no live lane. Use this value in a config file that the client reads only at startup. The live snapshots show this value only while a workernode is connected. Therefore Logos adds the historic maximum that it stores for each model in `model_profiles` (`max_reported_context_length`). The profile upsert maintains this value as a high-water mark. The value is known when **all** workernodes are offline. In that state the claude-logos wrapper sizes a session from this value, not from a client-side guess. |
| `max_model_len`             | A copy of `max_model_len_current_min` under the name that vLLM uses. An OpenAI-compatible client that already reads this field continues to work. |

The webservice (Spring) gets the first three values on `GET /internal/model_context_windows` as `stats` (`current_min`, `current_max`, `overall`). The original flat `windows` map (model to smallest window) is also in the response. It is older than `stats`. The UI gets the values as `context_window_current_min`, `context_window_current_max` and `context_window_overall` on `GET /me/keys/{id}/models`.

Source: `_served_context_window_stats()` in `logos/main.py`.

## 2. Placement floor: do not create a narrow lane

The narrowest lane sets the window that Logos tells each client. Thus a worker can refuse to host a model below a share of the context length of the model. Set the floor **for each model in the `config.yml` of the worker**. The hardware of the worker decides which windows the worker can reach.

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

The value is part of the model profile in the runtime snapshot of the worker. Thus the server uses the new value without a restart. Logos enforces the floor in two places:

- `_passes_minimum_load_feasibility`: the planner does not *propose* a load that cannot reach the floor.
- `_select_kv_mb_max_model_len_pair`: this function also limits the pair that Logos chooses at load time. Some load paths bypass the gate: contention, eviction-backed cold load and request-time cold load. These paths cannot place a below-floor lane without a log entry. Sometimes such a path must place a lane because a request is already waiting. Then it takes the **widest** pair that fits, not the narrowest. It also writes a log line that says the lane is below the floor.

Look for these two log lines when Logos does not place a model:

```text
Feasibility FAILED for <model>: smallest calibrated KV pair serving >=N context tokens needs …
Feasibility FAILED for <model>: no calibrated KV point serves the required minimum of N context tokens (widest is M)
```

The first line is temporary. It goes away when VRAM becomes free. The second line does not go away. No calibrated point on that node reaches the floor at any KV size. Do one of these actions: decrease `min_context_fraction` for that model, or re-calibrate the model.

The floor never blocks a model with an unknown context length. The floor stops the planner from *choosing* a narrow window. It is not a gate on calibration. A separate gate does that: `_passes_minimum_load_feasibility` refuses to load a model that was never calibrated on that node. The exception is a Metal/MLX provider. A Metal/MLX provider uses override profiles from the operator, because calibration is not possible there by design.

## 3. Context-aware routing: send long requests where they fit

`_prefer_deployments_with_context_room` (`logos/main.py`) estimates what a request needs. It removes the deployments that cannot serve the request.

```text
needed = prompt tokens + the output the request reserved + 3000 tokens of margin
```

**Source of "the output the request reserved":** the request states it. The field is `max_tokens` (Anthropic Messages, chat completions), `max_completion_tokens` or `max_output_tokens` (Responses API), whichever is present. If a request names none of these fields, Logos assumes that the request reserves 20,000 tokens. An uncapped request can generate until it reaches the window. The value 20,000 is the largest default among the clients that Logos serves. This is important because vLLM counts input and output against one budget. A prompt that fits alone can overflow when the requested reply is reserved.

**Source of the 3000:** it is the margin that Claude Code keeps between its own hard stop and the limit that it received. If Logos uses the same number, then a session that Claude Code considers safe is also safe for this filter. The margin absorbs the difference between the estimate and the real count of the tokenizer of the worker. The estimate (`logos/context_budget.py`) counts characters and divides by 3. It skips base64 attachments. It rounds against itself at each step. An estimate that is too high costs a deployment with more room. An estimate that is too low costs a 400 error.

The margin is part of `needed`. The lane does not need to hold it in addition. For example, a lane that serves 33,000 tokens must fit `prompt + output + 3000 ≤ 33000`. Thus the lane never has to "first make room" for the margin. The lane only needs 3000 tokens more than the request strictly needs.

There are two deliberate exceptions:

- **Logos always keeps a deployment with an unknown window.** Cloud providers have no window. Lanes that did not report a window yet also have none. This is missing information, not evidence of a narrow window. Thus `max_model_len_current_min` is a promise only across the deployments with a known window. A request sized from it can still reach a deployment with an unknown window.
- **If nothing fits, Logos returns the widest deployments** and not an empty list. The request then fails upstream with the limit in the error message. This is the behavior from before the filter existed. The alternative is a 404 that names no model.

Logos does not filter audio uploads. A transcription hint has a few words. It does not show how much context the request needs.

## 4. Clients

### Claude Code: the `claude-logos` wrapper

`logos-ui/public/claude-logos.sh` (and `.ps1` for Windows) is available at `<logos-url>/claude-logos.sh`. The AI Tools page installs it. At each start, the wrapper sends `GET /v1/models`, prints the window that it got, and exports the result into its own child process. The wrapper does not change anything outside itself. Thus plain `claude` continues to use an Anthropic subscription with no change.

`LOGOS_MODEL` is optional. If it is not set, Claude Code finds the Logos models from the listing, and you change the model with `/model`. If it is set, Logos pins each Claude Code model slot (`opus`, `sonnet`, `haiku`, …) to that id. This is a useful default. The setup flow does not need it.

Each Claude Code model slot always names a Logos model, also when `LOGOS_MODEL` is not set. The slots are `ANTHROPIC_MODEL`, the `opus`, `sonnet`, `haiku` and `fable` defaults, the small/fast model and `CLAUDE_CODE_SUBAGENT_MODEL`. Without a pin, they all name the session default. The session default is `LOGOS_DEFAULT_MODEL` if Logos lists it. Otherwise it is the first model in the Anthropic listing that is not an embedding, reranking, speech or image model. An exact id wins over its `claude-` form. `/model` then switches the main loop from there. Without this, each slot falls back to an Anthropic id: the model saved in `~/.claude/settings.json` (for example `claude-opus-5-5`), or the built-in default of the alias. Logos does not serve these ids. Claude Code sends some requests with a slot model on its own, also after `/model` switched to a Logos model; the session title is one of them. Logos answers each of these requests with `No deployment found for model 'claude-opus-5-5'` (or `Model … not available for this key`). `ANTHROPIC_MODEL` also has a higher priority than the `model` in `~/.claude/settings.json`. Thus the default of the subscription does not get into a Logos session.

Claude Code shows a gateway model in `/model` only when the id contains `claude` or `anthropic`. Thus the Anthropic-shaped `GET /v1/models` lists each model once, as `claude-<id>` (`claude-Qwen/Qwen3.8-27B`). The display name is the plain name. There are no aliases. Logos lists an id unchanged in two cases. In the first case, the id already contains `claude` or `anthropic` (`my-Anthropic-proxy`, not `claude-my-Anthropic-proxy`). In the second case, the `claude-` form of the id resolves to another model. A request for `claude-<id>` resolves to `<id>`, unless a model with exactly that name exists. The plain name and the aliases continue to work in requests. The OpenAI-shaped listing does not change.

The wrapper also does two more things with the listing that it already has:

- **It warms the model up.** `POST /v1/models/{model}/warmup` tells the planner that the model is about to be used. It returns immediately. It records the same latent demand that the scheduler records when classification prefers a model that it did not get. It also starts the planner cycle early. Thus the cold load can overlap with the seconds that a developer needs to read the startup line. The warmup is a hint, not a reservation. The planner still decides with its own fairness rules. A warmup can never evict a lane that real traffic uses. Logos never sends an inference request for the caller. Warming a model that the key cannot access returns a 404. Warmup runs only when `LOGOS_MODEL` is pinned.
- **It names models that are new to you.** The wrapper compares the id list with the list from the last run (`~/.config/claude-logos/known-models`). It prints the additions. The first run records the baseline silently. It does not announce all models as new.

**Web search.** The `WebSearch` tool of Claude Code is a server-side Anthropic tool. The model call becomes a Messages request that carries `{"type": "web_search_20250305", ...}`. The API must run the searches and answer with `server_tool_use` / `web_search_tool_result` blocks. Logos does this task (`logos/anthropic_compat/web_search.py`). The server tool becomes a function tool for the model. The orchestrator searches each call on DuckDuckGo, through the proxy settings of the server. It never fetches the result pages. Logos then returns the turns folded into one Anthropic-shaped message. Each model turn goes through the normal pipeline. Thus routing, permissions and billing are the same as for any other request. A request can have up to 5 searches. `allowed_domains` and `blocked_domains` filter the results. Wrapper revisions before 6 denied `WebSearch` in their settings layer. Revision 6 removes that deny on start. To keep `WebSearch` off for a run, use `--disallowedTools WebSearch`.

`LOGOS_CONTEXT_SOURCE` selects the figure that sizes the session: `available` (default, `max_model_len_current_max`), `guaranteed` (`max_model_len_current_min`) or `max` (`max_model_len_overall`).

**The arithmetic is important, and it is not obvious.** Claude Code takes `CLAUDE_CODE_MAX_CONTEXT_TOKENS` and subtracts `min(CLAUDE_CODE_MAX_OUTPUT_TOKENS, 20000)` from it. It auto-compacts 13,000 tokens below that result. Thus:

```text
compacts at  = window − headroom − min(max_output, 20000) − 13000
hard stop at = window − headroom − min(max_output, 20000) − 3000
```

Two results follow:

1. **Do not subtract the output reservation yourself.** Claude Code already does this. A second subtraction loses 20,000 tokens of context for no reason. The old wrapper and the AI Tools page did this second subtraction. Example: the window is 111,200 tokens. The old wrapper also reserved 32,768 tokens for output and took 8,192 tokens of headroom. It compacted at 37,240 tokens. The same window now compacts at 75,976 tokens.
2. **A `CLAUDE_CODE_MAX_OUTPUT_TOKENS` value above 20,000 gives no benefit.** The reservation has a cap at 20,000 in all cases. A larger value only increases the `max_tokens` on the wire. The wrapper sets exactly 20,000.

**What happens when a session reaches the limit?** There are two steps, in this order. At `window − reserve − 13000`, Claude Code compacts the conversation by itself and continues. If a single turn grows past `window − reserve − 3000`, Claude Code does not send it. It asks for a `/compact` instead. Neither case is an error that the user must correct. The failure mode that these steps replace was a 400 from vLLM in the middle of a turn.

#### The floor: 37,024 tokens

The deductions above are fixed. Thus there is a window size below which Claude Code cannot run **at all**. This size is much higher than it seems. The opening prompt of Claude Code has the system prompt and the schemas of all its tools. It is approximately 13,000 tokens before the user types anything. Claude Code cannot compact it.

```text
floor       = 13000 opening prompt + 20000 reservation + 3000 hard stop + 1024 headroom  = 37024
comfortable = 13000 opening prompt + 20000 reservation + 13000 auto-compact + 1024        = 47024
```

A 32,768-token lane leaves `32768 − 20000 = 12768` tokens of input. This is one token less than the opening prompt. The **first** message of the session returns this error:

```text
This model's maximum context length is 32768 tokens. However, you requested
20000 output tokens and your prompt contains at least 12769 input tokens
```

There is nothing to compact. Thus the session never recovers. If the window is between the floor and 47,024 tokens, the session runs, but auto-compaction starts from the first message.

Two places enforce this, because the user can choose a model in either place:

- **The AI Tools page** disables such a model for Claude Code (`claudeCodeFitFor` in `ai-tools.ts`). It shows the window in the option label. It blocks the wizard on the model step and shows the arithmetic. OpenCode is not affected. OpenCode receives the value to reserve (`min(8192, context/2)`). Thus a narrow window costs OpenCode reply length, not the session. The page judges `max_model_len_current_min`. This is the figure that a request meets for each deployment that can answer. The page uses the wider figures only when `max_model_len_current_min` is absent. The page never judges a model that no lane serves.
- **The wrapper** refuses to start. It prints what is left, what it costs, and the `LOGOS_MAX_OUTPUT_TOKENS` value that fits. It measures against the auto-compact point, not the hard stop. A reservation that clears only the hard stop causes compaction on each turn. `--check` prints all of this and does not refuse anything. Run it when a session does not start.

The only client-side action is to decrease the reservation. At 32,768 tokens, `LOGOS_MAX_OUTPUT_TOKENS=5744` makes the model usable with shorter replies. The better action is to increase the window. See §2 and §3.

The old wrapper check (`headroom + reservation >= window`) found only a negative result. A 32,768-token window passes this check easily, but it is not usable.

The "auto-compact starts at ~60%" effect that started this work comes from the two fixed deductions. They are 33,000 tokens in total. They are a share of a window that was already too small. It is not a percentage, and no setting increases it. `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` exists, but `min(window × pct, window − 13000)` limits it. Thus it can only compact *earlier*. The only action is to increase the window. This is the purpose of §2 and §3.

The wrapper gives a warning for one more case. If a model id starts with `claude-` or contains `[1m]`, Claude Code resolves it to one of its own models. Claude Code then ignores `CLAUDE_CODE_MAX_CONTEXT_TOKENS` for it. `DISABLE_COMPACT=1` forces the window through, but auto-compaction is then off.

Useful commands:

```bash
claude-logos --check       connection, model and how much room a session would get
claude-logos --update      replace the wrapper with the current one
claude-logos --uninstall   remove the wrapper, its config and its key
claude-logos --help        this, then claude's own help
```

#### Revisions

`CLAUDE_LOGOS_VERSION` near the top of the script is a monotonic integer. Increase it in the same commit as each change that installed copies must receive. Keep `$ClaudeLogosVersion` in `claude-logos.ps1` at the same value. The revision exists only in this place. Logos serves the current wrapper at the same URL that an installed copy came from. Thus there is no second file to keep in sync, and the two cannot disagree.

Installed copies **never update themselves.** At most once a day, the wrapper fetches that URL in the background and records the revision that it found. At the next start, the wrapper compares the revision. If a newer revision exists, the wrapper prints the one command that replaces the script. Thus the notice costs no startup time. It appears one start after a release. This is soon enough, because the user must type the command anyway.

`--update` replaces the script and nothing else. The key, the config and the settings layer stay the same. Thus an update is not a new setup, and the user does not need to visit the AI Tools page again. `--update` validates the download before it replaces the script. The download must contain a revision line, and it must parse. Without this check, a captive portal or a proxy error page can overwrite a working wrapper with HTML. The user runs that file next. The replacement is a rename in one directory. Thus a copy that still runs continues to read the old inode and ends normally.

### OpenCode

OpenCode reads its config once at startup and cannot read it again. Thus the generated `opencode.json` states `max_model_len_overall`. This is the ceiling, not a number that becomes old. Logos can reject long conversations when capacity is low. The routing in §3 gives them the best chance.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Claude Code compacts much earlier than the window suggests | The output reservation is subtracted twice, or the session runs on `guaranteed` while `available` is much larger. Check `claude-logos --check`. |
| `claude-logos` refuses to start with `BLOCKED` | The window is below the 37,024-token floor, so the first request of the session is rejected. Choose a wider model, or use the `LOGOS_MAX_OUTPUT_TOKENS` value that the message names. |
| The first message of a session returns a 400 with `you requested 20000 output tokens` | The lane started narrower than the window that sized the session. This is the cold-start case. If no lane is up, only `max_model_len_overall` is known. That value is the widest window for which the model was ever calibrated. It is not what the planner gives to a new lane from the capacity that is free now. The next start sizes the session against the lane that is now up. |
| `maximum context length is N tokens` returns 400 | The request reached a deployment that is narrower than the estimate expected. Most likely this deployment reports no window. Change that wrapper to `LOGOS_CONTEXT_SOURCE=guaranteed`. |
| A model is never placed on a node | The node cannot meet the placement floor. Look for the "no calibrated KV point serves the required minimum" line. Decrease `min_context_fraction` for that model in the config.yml of the worker. |
| `max_model_len` is absent from `/v1/models` | No source reports a window that always holds. The cases are: a cloud model whose upstream publishes no window and whose registry entry names none; a vLLM lane at the native maximum of the model (the worker does not report this); or all workernodes are offline. In the last case, `max_model_len_overall` still has the historic maximum of the model. The claude-logos wrapper sizes the session from it (the startup line says "no lane is up yet"). |
