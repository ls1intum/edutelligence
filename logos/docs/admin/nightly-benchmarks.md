---
title: Nightly Benchmarks
---

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

## Enable, inspect and disable a schedule

See the [illustrated admin walkthrough](../roles/logos-admin.md#nightly-benchmarks)
for screenshots of the plan and both confirmation dialogs.

![Example schedule with the model, parameter values and dataset previews](../static/img/roles/logos-admin-nightly-benchmarks.png)

1. Sign in as a Logos Admin and open **Models**.
2. Open the model's **Model Details → Performance** tab.
3. Find the **Nightly benchmarks** card for the intended worker.
4. Review **Model** and **Parameters to be tested**.
5. Select **Enable nightly runs…**, then confirm **Enable nightly runs**.
6. Check that the card shows **Nightly runs activated**.

The schedule persists after a page reload or browser close. To remove the pair
from rotation, select **Disable nightly runs…** and confirm **Disable nightly runs**.
Cancelling either dialog leaves the saved state unchanged. Activation requires
an updated, connected worker. Run admission also checks the lane and the other
available workers.

The card shows a plan for this pair, not a guaranteed reservation for tonight.
The scheduler selects eligible pairs at runtime. The dataset editor and question
previews below the card remain available for manual runs; they do not alter the
nightly workload.

The next day, expand **Latest nightly results** and inspect each configuration's
outcome, attempt and benchmark ID. Use the performance comparison below for
successful measurements. A finished plan can contain failed configurations;
review individual outcomes before comparing throughput.

## Automatic pair rotation

Each night admits at most 2 enabled model/worker pairs, one after the other.
Pairs without a previous attempt come first, followed by the oldest previous attempt.
The pair ID determines the order when previous attempt dates match.
The scheduler skips unavailable pairs before admission; they do not consume a slot.
The scheduler excludes disabled pairs.

The quota counts admitted pairs, including failed or cancelled plans. All
parameter configurations and the bounded retry belong to the same pair's slot.
The count persists across application restarts and disabling/re-enabling a
schedule cannot reset it. The next Berlin calendar date has a fresh quota.

The 04:50 admission cutoff can leave fewer than 2 pairs tested. Remaining
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
- During measurement, 5 minutes without output content or a successful
  request completion stops the run. Transport and lease heartbeats do not
  count. This watchdog also applies after 05:00.
- A stalled run gets at most 1 retry with the same configuration, after a
  worker-lane restart, and only before 04:50. A second stall skips that
  configuration. Configuration errors are recorded and skipped without retry.
- Preparation and warm-up have a separate 15-minute budget. Worker draining
  also has a 15-minute budget. Cleanup can finish after the nominal window.

The watchdog checks progress every 1 s. The scheduler checks eligible schedules
every 15 s. These intervals do not guarantee an exact response time.

## Workload and parameter plan

Each nightly plan starts with the current production configuration.
If explicit positive values are known, then it tests `max_num_seqs` and
`max_num_batched_tokens` at approximately 75% and 125% of their current values.
It changes only 1 parameter at a time. With sequence limit 16 and batch-token
limit 4096, the candidate configurations are:

| Configuration | `max_num_seqs` | `max_num_batched_tokens` |
|---|---:|---:|
| Current configuration | 16 | 4096 |
| Lower sequence limit | 12 | 4096 |
| Higher sequence limit | 20 | 4096 |
| Lower batch-token limit | 16 | 3072 |
| Higher batch-token limit | 16 | 5120 |

Invalid combinations are skipped. If these values are unknown, only the
reference configuration runs.

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

Model profiles and calibration snapshots use the central Logos database.
Workers fetch their profiles before lanes start and receive central changes through `sync_model_profiles`.
The nightly schedule and recovery journal use the same PostgreSQL database.
Benchmark runs do not restore local profile files.

Apply `058_central_model_profiles.xml` and the nightly migration before workers connect.
Imported profiles are stale until calibration succeeds.
Automatic calibration runs first during the maintenance window.
Benchmarks use the remaining time.

Deploy webservice migrations `061_nightly_benchmarks.xml` and `062_maintenance_calibration.xml`, the orchestrator,
the web application and the updated worker code. Workers advertise
`supports_benchmark_restart`; activation rejects workers without this feature.
Enable only the desired model/worker pairs after deployment. No schedules are
enabled by the migration or by application startup.

## Calibration priority and shared execution

Automatic calibration remains enabled by default, from 03:00 to 05:00 in `Europe/Berlin`.
The `LOGOS_CALIB_WINDOW_START`, `LOGOS_CALIB_WINDOW_END` and `LOGOS_CALIB_TIMEZONE` variables control calibration.
`LOGOS_CALIB_ENABLED=false` disables automatic calibration. It does not disable manual calibration.
These variables do not change the benchmark time limits.

Calibration has priority. A healthy worker with pending calibration blocks new benchmarks during the calibration window.
Each worker gets at most 1 automatic calibration attempt per window.
Benchmarks start only after these attempts finish and before 04:50.
If new calibration work appears during a benchmark, the current run finishes first.
The scheduler restores the worker and stops the remaining benchmark plan with `calibration_pending`.

At most 1 calibration or benchmark runs across the cluster.
This limit also applies to manual calibration and manual benchmarks, including cloud benchmarks.
Conflicting manual starts return HTTP 409. They do not enter a queue.
Automatic calibration stops at the end of its window. The 50% completion rule applies only to benchmarks.

PostgreSQL stores the active calibration and manual benchmark claims.
A worker must confirm that calibration ended before the orchestrator releases its claim.
A timeout or a terminal event alone does not release it.
Update workers before use: the coordinator requires the `get_calibration_status` command.
Manual benchmarks retain their claim until process cleanup completes.

If a calibration start has no reply, the claim stays active.
Use the calibration stop action after the worker reconnects.
The stop action confirms worker completion before it releases the claim.
Automatic calibration also sends this stop command after its window closes.

An orchestrator crash can leave a manual benchmark claim or an active job record.
Age alone does not release these records.
An operator must stop the original benchmark process and verify worker cleanup before database recovery.
Then mark the affected job as failed and remove its matching `maintenance_benchmark` record.
Keep every nightly recovery journal until the scheduler restores the original worker configuration.

## Deployment recovery

A schedule retains its recovery journal independently of the model/provider
deployment. Deleting a deployment must not delete the original settings needed
to restore its worker. Schedules whose deployment no longer exists are disabled.

## Status and activation API

The webservice requires the `logos_admin` role for both endpoints. The web
application uses the `/api` prefix; the webservice paths below omit that prefix.
The orchestrator's corresponding `/internal/model_benchmarks/nightly/*` routes
require the shared internal secret.

| Webservice endpoint | Request |
|---|---|
| `POST /logosdb/model_benchmarks/nightly/status` | `{ "model_provider_id": 31 }` |
| `POST /logosdb/model_benchmarks/nightly/configure` | `{ "model_provider_id": 31, "enabled": true, "expected_enabled": false }` |

`model_provider_id` identifies a deployment pair, not a model ID or provider ID.
To disable an enabled schedule, send `enabled: false` and `expected_enabled: true`.
A stale expected state returns HTTP 409. Enabling also returns 409 if the worker
lacks restart support or the pair still requires recovery.

Status includes `enabled`, `status`, `last_run_date`, `report`,
`recovery_required`, `plan` and `timezone`. A new, unsaved schedule can omit
`last_run_date`. The raw recovery journal is not exposed. The activation response
contains the saved status; use the status endpoint for the parameter plan.
`last_run_date` records admission, including failed attempts, rather than the
last successful measurement. The current pair limit is the code constant
`MAX_PAIRS_PER_NIGHT = 2`, not a UI or environment setting.

## Operational states

| State | Meaning and next action |
|---|---|
| `scheduled` | Enabled and waiting in the rotation. Check the time window and other pairs' priority. |
| `unavailable` | Admission skipped the pair. Read the report for worker, lane or capacity requirements. No nightly slot was consumed. |
| `preparing` / `running` | The pair has a nightly slot. The scheduler reserves the worker and executes its plan. |
| `completed` | The plan finished. Inspect individual outcomes; this does not mean every configuration succeeded. |
| `window_closed` | No further configuration can start after 04:50. |
| `window_closed_below_half` | The 05:00 check found fewer than 25 of 50 successful completions. |
| `preparation_timeout` / `stalled` | Preparation exceeded its budget, or measurement stopped making progress. Inspect the attempt report. |
| `recovery_required` | The original configuration is not ready. Resolve the worker error; keep the reservation and journal intact. |
| `interrupted_recovered` | The scheduler restored a worker from its persisted recovery journal. |
| `disabled` | The pair is excluded from future rotation. Check `recovery_required` before assuming cleanup is complete. |

A restart, a failed run or an opt-in change does not clear the nightly quota.
If fewer than 2 pairs run, check eligibility, existing manual jobs, recovery
and the 04:50 cutoff. One long pair can use the available admission window.

## Validation

Unit tests cover admission boundaries, daylight-saving transitions, the 50%
threshold, inactivity, disable, cancellation, retries and recovery. PostgreSQL
integration tests in `tests/integration/benchmarks/test_nightly_store.py` use an
explicit `NIGHTLY_TEST_DB_URL` and create an isolated temporary schema. They use
the production database manager's transaction-close behavior.

For a PostgreSQL integration run, use an isolated test database and the full
orchestrator dependencies. Exclude the unit-test conftest, which replaces SQLAlchemy
with stubs:

```bash
# From logos/logos-orchestrator; use a disposable database URL.
NIGHTLY_TEST_DB_URL="$TEST_DATABASE_URL" \
  uv run pytest --noconftest tests/integration/benchmarks/test_nightly_store.py -q
```

Before the first production activation, deploy the complete change to a test
environment with supported workers. Validate an actual benchmark and stored
result, the confirmation controls, quota rotation, cancellation, retry and
restoration. Exercise 04:50 and both sides of the 05:00 threshold with a
controlled test clock. Verify that other workers still accept production traffic.
A UI or database test alone does not verify an overnight run on real GPU hardware.
