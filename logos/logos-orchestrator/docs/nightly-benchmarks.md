# Nightly benchmarks

The first implementation provides `logos.benchmarks.nightly.run_nightly_benchmark_batch`,
a time-window guard around the existing sequential benchmark batch runner.
It admits batches from 03:00 (inclusive) until 05:00 (exclusive), Europe/Berlin,
including daylight-saving changes. Starting late uses only the remaining window.
At 05:00 it requests cancellation of the active run and waits for cancellation
cleanup before raising `TimeoutError`; cleanup can finish after the deadline.
Outside the window it returns `False` without invoking the run callback.
It preserves the configured workload and output-token settings.

This helper is not yet called by the application lifecycle: automatic nightly
runs are not enabled. The existing calibration schedule is unchanged.

Before enabling nightly execution:

- Connect the helper to an application-owned nightly trigger, with persistent
  run tracking to prevent duplicate batches after restarts or across replicas.
- Reserve at most one server node cluster-wide, isolate it from production
  traffic, and release the reservation on completion, cancellation or failure.
- Sequence the selected nodes and models within the remaining nightly window.
- Replace the calibration maintenance-window trigger with benchmark scheduling,
  preserving the calibration needed to make models available for production.
- Store and summarize results for morning review, using `log_entry` for
  production workload evidence and throughput as the main metric. Keep workload
  and generation settings comparable; include latency and failure rates.

Automatic production parameter changes are a later iteration.
