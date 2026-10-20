---
title: Model Benchmarks
---

# Model Benchmarks

Use **Model Details → Performance** to measure a model on a specific provider.
You need the **Logos Admin** role to start a benchmark.
These measurements show serving performance. They do not grade the generated answers.

## Before you start

For a Logos worker, check that the worker is connected and has sent its first status report.
The orchestrator must have capacity planning available.
An offline worker cannot run the benchmark.

A Logos worker benchmark needs no separate provider endpoint or provider API key.
An external provider benchmark uses its configured endpoint and credential.
Only one benchmark job can run on a provider at a time.

## Configure a run

1. Open **Models → Model Management**.
2. Select the model.
3. Open **Performance → Run benchmark**.
4. Select the worker or provider.
5. Set the sample size.
6. Open **Dataset and settings** to change the dataset, request profile or output limit.
7. If necessary, change the vLLM settings for the selected Logos worker.
8. Open **Repeat or compare settings** to configure a batch.

The default dataset is `openai/gsm8k`, variant `main`, split `test`, with the `question` prompt column.
The default run uses 50 samples, a sequential profile, seed 42 and at most 512 output tokens per request.
One warm-up request runs before measurement. Its result is not part of the measurement.

| Setting | Supported values |
| --- | --- |
| Sample size | 1–100 requests per run |
| Maximum output tokens | 1–4096 per request |
| Concurrent requests | 1–32 |
| Dataset | Public Hugging Face dataset with a plain-text prompt column |
| vLLM overrides | Logos workers only |

Open **Dataset preview** to show up to five example rows.
**Open in Hugging Face** opens the selected dataset variant and split.
Private datasets, gated datasets and structured conversation columns are not supported by this editor.
The orchestrator downloads the dataset when the job starts.
A small sample size does not necessarily limit the dataset download size.

### Desktop example

The screenshot shows the actual Performance component with synthetic example data.
It omits the application shell and live services. It does not verify a GPU run.
**Run benchmark** contains the provider, sample size and start action.
Dataset settings and batch options stay collapsed until needed.
**Results** contains the charts and run history.
The settings remain unchanged when you switch between these views.
Active runs on other providers remain visible in both views.

![Desktop benchmark setup](/img/benchmarks/performance-desktop.png)

## Confirm the start

1. Select **Review benchmark**, or **Review batch** for a batch.
2. Check the provider, dataset, sample size, run count and production traffic information.
3. Select **Start benchmark** to submit the job, or **Cancel** to close the dialog.

The dialog uses the same confirmation component as team deletion.
Closing the dialog does not start a job.
Closing the browser after confirmation does not stop a submitted job.
After a successful start, **Results** opens and shows the job status.
If the start fails, **Run benchmark** keeps your settings and shows the error.

The screenshot shows the confirmation dialog with synthetic example data.
The message explains when production requests can use the selected model lanes again.

![Desktop benchmark confirmation dialog](/img/benchmarks/confirmation-desktop.png)

## Production traffic during a benchmark

Logos automatically reserves all lanes for the selected model on the selected worker.
The reservation starts before benchmark preparation and remains active until job cleanup.
It also covers replacement lanes and the intervals between batch runs.
There is no permanent benchmark-only lane setting.
Other models on the same worker remain available.

Existing admitted requests finish before measurement starts.
New production requests wait or use another eligible provider, subject to normal request limits and timeouts.
Authenticated benchmark requests can use the reserved lanes.
The capacity planner does not reclaim those lanes during the job.

Completion, failure and cancellation release the reservation.
A drain timeout fails preparation instead of starting measurement with existing requests still active.

External provider benchmarks do not reserve provider capacity.
Other traffic on that provider can affect the measurements.

## Run a batch

1. Open **Repeat or compare settings** and enable **Run a batch**.
2. Set the repetitions per configuration.
3. Add the parameters to vary.
4. Enter each value list or numeric range.
5. Check the configuration preview.
6. Select **Review batch** and confirm the batch.

One confirmation starts the complete batch.
Each configuration repeats before the next configuration starts.
Multiple varied parameters produce all combinations.
The limits are 1,000 configurations and 10,000 total runs.
The sample count applies separately to each run.
If the configurations use different sample counts, the confirmation shows their minimum and maximum.

The reservation remains active between configurations and repetitions.
The first failed run stops the remaining batch. Completed measurements remain stored.
Use the run's cancel action to stop the batch.
Worker disconnects and orchestrator restarts stop the job. Batches do not resume automatically after a restart.

## Read the comparison charts

Open **Results**.
Select a reference run and a metric in **Compare benchmark runs**.
Each chart varies one parameter while the other recorded settings match the reference.
The charts use separate vertical scales to show their measured ranges.

One eligible measurement appears as a filled point, including when repetitions is 1.
The label `n = 1` means one measured run. That run can contain many sample requests.
Multiple measurements use a boxplot. The box shows the middle 50%; the line shows the median.
Separate dots show outliers.

A result must be successful and complete, with the required configuration metadata.
Logos does not infer missing controls in historical results.
If a result is absent, check its completion state and recorded configuration.

The desktop example shows one completed measurement and its recorded settings.
It uses the same synthetic data as the setup example.

![Desktop comparison charts and run history](/img/benchmarks/results-desktop.png)

### Mobile example

At a 375px viewport, the setup fields and comparison charts stack vertically within their separate views.
The single-run points remain visible. These screenshots use the same synthetic data as the desktop examples.

<details>
<summary>Show the mobile benchmark setup</summary>

![Mobile benchmark setup](/img/benchmarks/performance-mobile.png)

</details>

<details>
<summary>Show the mobile results</summary>

![Mobile comparison charts and run history](/img/benchmarks/results-mobile.png)

</details>

The mobile confirmation dialog contains the same reservation message and actions.

<details>
<summary>Show the mobile confirmation dialog</summary>

![Mobile benchmark confirmation dialog](/img/benchmarks/confirmation-mobile.png)

</details>

## Change settings and retry a failed model

**Use for next benchmark** copies a historical run's settings and opens **Run benchmark**.
It does not change the stored result.
Blank vLLM fields preserve the current worker values. Explicit `false` values remain overrides.

When you submit corrected serving settings for a failed or stopped lane, Logos applies them before another startup attempt.
Unchanged settings do not make a failed lane ready.
The worker must report the applied configuration and a ready lane before measurement starts.

This behavior does not repair an offline worker or insufficient GPU memory.
It also does not make unsupported model and attention-backend combinations compatible.
Open **View error details & configuration**, correct the cause, and start another run.
There is no automatic retry or attention-backend search.

Changed vLLM settings remain active after completion, failure or cancellation following reconfiguration.
There is no automatic rollback. Restore the intended serving settings explicitly when necessary.
**Clear vLLM changes** only clears draft overrides. **Stop varying** only removes a parameter from the sweep.

## Verify on Dev

Use a connected GPU worker with a ready model.
The CI forwarding-overhead benchmark uses a mock lane. It does not replace these checks.

1. Start a normal request, then confirm a benchmark for the same model and worker.
2. Check that the existing request finishes before measurement starts.
3. Send production requests during the benchmark.
4. Check that production requests wait or use another provider while benchmark requests succeed.
5. Run one configuration with one repetition and check the point and `n = 1` label.
6. Run a batch and check that its reservation remains active between runs.
7. Cancel a job and check that production traffic can use the model after cleanup.
8. Repeat the release check after a successful job and a failed job.
9. Correct settings for a failed lane and check that reconfiguration occurs before another startup attempt.
10. Restore the intended serving settings after the checks.

## Reload worker GPU limits

Open **Run benchmark → Dataset and settings → vLLM settings for the next run**.
Select **Reload GPU limits**.
The button stays available after a failed request or an unknown GPU count.

![Desktop view of the GPU limits reload button](/img/benchmarks/gpu-limits-desktop.png)

The desktop view shows **Reload GPU limits** above the vLLM fields.

![Mobile view of the GPU limits reload button](/img/benchmarks/gpu-limits-mobile.png)

The mobile view keeps the reload button above the configuration fields.
These screenshots use example data in the local Performance component.

Wait for the worker status update if the GPU count stays unknown.
Then select **Reload GPU limits** again.
Use **Clear vLLM changes** to keep the current worker configuration.

Requests admitted before a benchmark reservation finish before the benchmark starts.
New production requests cannot use the reserved model lanes.
Reserved lanes do not contribute memory to capacity reclaim plans.
After cancellation, wait for cleanup before another benchmark starts on that worker.
A conflicting start returns HTTP 409 without a new pending job.
A failed lane can restart with its current settings when you explicitly apply those settings again.
