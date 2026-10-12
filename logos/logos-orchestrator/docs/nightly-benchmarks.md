# Nightly benchmarks

Logos admins enable or disable a nightly schedule for each model/worker pair on
**Model Details → Performance**. Both actions require confirmation. Schedules
show the model and concrete parameter values to be tested, above the existing
dataset editor and question previews. Unknown serving limits show a
current-configuration-only plan. The preview reflects the worker's current
settings; the scheduler builds the plan again when the nightly run starts.

Schedules are off by default and persist in PostgreSQL. The nightly plan is independent
of the manual benchmark editor. Disabling a schedule cancels its active run and
restores the worker before it returns to production.

## Automatic pair rotation

Each night admits at most two enabled model/worker pairs, sequentially. Pairs
that have never run come first, followed by the oldest previous attempt, with
pair ID as a stable tie-breaker. Offline or otherwise unavailable pairs are
skipped before admission and do not consume a slot. Disabled pairs are excluded.

The quota counts admitted pairs, including failed or cancelled plans. All
parameter configurations and the bounded retry belong to the same pair's slot.
The count persists across application restarts and disabling/re-enabling a
schedule cannot reset it. The next Berlin calendar date has a fresh quota.

The 04:50 admission cutoff can leave fewer than two pairs tested. Remaining
pairs keep their priority for the next night. Recovery of an interrupted worker
always happens before selection, even when tonight's quota is already full.

## Time and failure policy

All times use `Europe/Berlin`, including daylight-saving changes.

- Start configurations and retries from 03:00 inclusive to 04:50 exclusive.
- At 05:00, stop an active run with fewer than 50% of its measured requests
  successfully completed. Started requests and output tokens do not count
  toward this percentage. With 50 samples, at least 25 must have completed.
- At or above 50%, let the current configuration finish. Do not start another
  configuration afterwards. The runner's two-hour measurement timeout remains
  an outer limit; the preparation budget is separate.
- During measurement, five minutes without output content or a successful
  request completion stops the run. Transport and lease heartbeats do not
  count. This watchdog also applies after 05:00.
- A stalled run gets at most one retry with the same configuration, after a
  worker-lane restart, and only before 04:50. A second stall skips that
  configuration. Configuration errors are recorded and skipped without retry.
- Preparation and warm-up have a separate 15-minute budget. Worker draining
  also has a 15-minute budget. Cleanup can finish after the nominal window.

The watchdog polls once per second. The scheduler checks eligible schedules
every 15 seconds. Neither is a real-time clock guarantee.

## Workload and parameter plan

Each nightly plan starts with the current production configuration. Where
explicit positive values are known, it tests `max_num_seqs` and
`max_num_batched_tokens` at approximately 75% and 125% of their current values,
changing only one parameter at a time. Invalid combinations are skipped. If
these values are unknown, only the reference configuration runs.

Every configuration uses GSM8K `main/test`, the `question` column, 50 requests,
512 maximum output tokens, concurrent profile with concurrency 4, and seed 42.
Quantization, context length and model weights are not search parameters.
The fixed output cap is not itself an optimization parameter.

Completed GuideLLM reports are stored in `model_provider_benchmarks` and appear
in the existing performance comparison. Internal inference requests use the
existing `log_entry` logging path. The nightly control shows per-configuration
outcomes, retries and benchmark IDs. Failed or incomplete runs are not stored
as successful throughput measurements. This iteration does not replay
production requests or automatically apply winning parameters.

## Worker ownership and recovery

One PostgreSQL advisory lock serializes nightly plans across the cluster and
excludes new manual benchmarks during the nightly maintenance slot. A persisted
local-date claim prevents re-running a schedule after an application restart.
Existing manual benchmarks finish before nightly admission.

The selected worker must be online, healthy and not calibrating. Another
healthy worker must remain available. The model must have exactly one existing,
loaded and awake vLLM lane. Production requests cannot enter the reserved node;
existing traffic drains before a benchmark starts. Other workers remain
available. Normal capacity-planner and manual lane mutations cannot alter the
reserved node.

Original settings are journaled before mutation and restored after the plan,
on cancellation and before a retry. Cleanup restarts the lane even when the
settings did not change. A failed restart that removed the lane can recreate it
from its original configuration. If restoration fails, the reservation and
journal remain, and further nightly plans pause. The scheduler retries recovery
before admitting other work, including after an application restart. It does
not interrupt existing production requests if initial draining fails before
any benchmark changed the worker.

The application retains its existing single-orchestrator routing architecture;
this feature does not introduce multi-process worker-session sharing.

## Deployment

Deploy the webservice migration `057_nightly_benchmarks.xml`, the orchestrator,
the web application and the updated worker code. Workers advertise
`supports_benchmark_restart`; activation rejects workers without this feature.
Enable only the desired model/worker pairs after deployment. No schedules are
enabled by the migration or by application startup.

The automatic calibration maintenance timer is replaced by this scheduler.
Explicit calibration actions and worker calibration remain available. The old
`LOGOS_CALIB_WINDOW_*` environment variables no longer control an application
startup timer.

A schedule retains its recovery journal independently of the model/provider
deployment. Deleting a deployment must not delete the original settings needed
to restore its worker. Schedules whose deployment no longer exists are disabled.

## Validation

Unit tests cover admission boundaries, daylight-saving transitions, the 50%
threshold, inactivity, disable, cancellation, retries and recovery. PostgreSQL
integration tests in `tests/integration/benchmarks/test_nightly_store.py` use an
explicit `NIGHTLY_TEST_DB_URL` and create an isolated temporary schema. They use
the production database manager's transaction-close behavior.
