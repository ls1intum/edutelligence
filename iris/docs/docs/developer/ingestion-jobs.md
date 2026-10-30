---
title: Ingestion Jobs
---

# Ingestion Jobs

A lecture-unit ingestion run is long: it may download a video, transcribe it, and send every slide of a deck through a vision model before it writes anything. During all that time Artemis can dispatch a newer request for the same unit — the instructor replaced the slides, a retry fired, a revoked lease was reclaimed elsewhere.

Two runs for one unit must not both finish. They write the same rows, so the loser can overwrite the winner's content, and whichever reports last decides what Artemis believes about a unit it has already moved on from. `IngestionJobHandler` resolves that by letting the newer run **supersede** the older one.

This page covers job identity and cancellation. For what the pipelines actually do with the content, see the [RAG pipeline](./rag-pipeline.md).

## Job identity

`ingestion_job_handler` is a process-wide singleton holding a registry of running jobs:

```python
IngestionJobKey = tuple[str, int, int, int]  # base_url, course_id, lecture_id, lecture_unit_id

_running_jobs: dict[IngestionJobKey, Event]
```

The Artemis base URL is part of the key, so one Iris instance serving several Artemis deployments never confuses their units. The value is the job's **cancellation event**, which doubles as its identity: the registry says "this unit is currently owned by the run holding this event".

## Starting a job supersedes the previous one

Every job Iris accepts starts immediately. There is no throttling here — Artemis controls how many jobs are in flight, and queuing them in Iris would only make Artemis' view of what is running wrong.

`add_job()` holds the unit's [update lock](#the-per-unit-lock) and the registry lock while it:

1. returns `False` without doing anything if the new job's own event is already set — a claim revoked before it started must not cancel a newer run of the same unit;
2. sets the previous job's event, if there is one, and counts the supersession;
3. registers the new event as the unit's current job; and
4. starts the thread, removing the registration again if the start itself raises — no worker would ever call `complete_job()` for it, and the unit would stay registered as running forever.

`complete_job()` removes the registration only when the stored event is still the caller's. A superseded run that finishes its unwinding after its replacement registered must not deregister the replacement.

## Cancellation is cooperative

A Python thread cannot be killed safely, so a superseded run is asked to stop and does so at its next checkpoint. There are two kinds, and they are not interchangeable.

### `raise_if_cancelled()`

A cheap read of the event that raises `IngestionCancelledException` when it is set. It belongs:

- at the boundary of expensive work — between slides, between embeddings, before a vision call;
- immediately before any Weaviate mutation; and
- **never** inside a delete/insert pair, which would leave the unit half-written.

That last rule is the one to keep in mind when adding a checkpoint. Stopping is only an improvement if what is stored stays consistent.

### `current_job_guard()`

A context manager for the write phases. It takes the unit's update lock, re-reads the registry **under** it, and raises `IngestionCancelledException` when the run has lost the unit:

```python
with ingestion_job_handler.current_job_guard(
    base_url, course_id, lecture_id, lecture_unit_id, cancel_event, "terminal callback"
):
    callback.finish(...)
```

The difference from `raise_if_cancelled()` is the identity check: an event that was never set but whose registration has been replaced also fails here. A run that passed a bare event check microseconds before a supersession would otherwise write anyway. Everything that must not interleave with a newer run — the chunk replacement, the stale-row purges, the terminal callback — goes through the guard.

What it actually decides, and what it does not:

| Situation                                                  | Outcome                                                          |
| ---------------------------------------------------------- | ---------------------------------------------------------------- |
| `cancel_event` is set                                      | Raises.                                                          |
| A **different** event is registered for the unit           | Raises — the run was superseded.                                 |
| `cancel_event` is the registered one                       | Proceeds, holding the lock for the body.                         |
| **No** event is registered for the unit, and ours is unset | Proceeds. An absent registration is not treated as a lost claim. |
| `cancel_event` is `None`                                   | Yields immediately. No lock is taken and nothing is checked.     |

:::warning Not an authorization check
The last two rows are the ones to know. The guard asks "has this run been superseded?", not "is this run entitled to write?" — so it does **not** reject a write from a run the registry has never heard of. A pipeline constructed without a cancellation event (the `None` default, as in tests and any direct instantiation) bypasses it completely, and a run whose registration was already removed still passes. Do not reach for this guard to keep unregistered writers out; it has no way to tell one from a legitimate untracked run.
:::

Neither exception matters for the tracked path, where `add_job()` registers the event before the thread starts and `complete_job()` removes it only after the worker is done. The pull-based worker, the only way lecture ingestion jobs reach Iris, goes through that path.

### The per-unit lock

`lecture_update_lock(base_url, course_id, lecture_id, lecture_unit_id)` serializes content, metadata and visibility writes for one unit. Locks are kept in a `WeakValueDictionary`, so a unit that is not being written to holds no lock object.

It is what makes the guard's identity check meaningful: supersession in `add_job()` and the ownership check in `current_job_guard()` take the same lock, so a job cannot be superseded between the check and the write it guards.

## A cancelled run stays silent

`IngestionCancelledException` is caught at two levels — in `LectureIngestionUpdatePipeline._run()` and again in the worker — and both **return without sending any terminal status update**.

This is the part worth preserving. By the time a run is superseded, Artemis has switched to the replacement's token; a `fail` from the old run is either dropped or, worse, marks the unit broken while its replacement is working on it. `tests/test_ingestion_cancellation_reporting.py` pins both halves of that: a cancelled run calls neither `fail` nor `finish`, and an _uncancelled_ failure still reports as a failure, so the silent path cannot start swallowing bugs.

Ordinary failures are unaffected and keep their error classification — a transcription failure, a vector-database failure and a PDF failure remain distinguishable to Artemis.

## Where cancellation events come from

| Trigger                                        | Path                                                                                                                                                                        |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A worker claiming a unit it is already running | The worker creates a fresh event and calls `add_job()`, which sets the previous one, so a newer job or a reclaimed-lease retry replaces the prior run instead of racing it. |
| Artemis revoking a run on a heartbeat          | The worker sets the run's event directly. A job still waiting to start is signalled the same way, and `add_job()` then refuses to start it.                                 |

In both cases the stopping mechanism is the same event and the same checkpoints. A revoked run stays counted against the worker's capacity until its thread actually exits, so capacity accounting cannot drop a still-live run.

:::note Not every ingestion route is tracked
Only lecture-unit ingestion goes through `IngestionJobHandler`. FAQ ingestion, FAQ deletion and lecture deletion start their own threads and are neither superseded nor cancellable.
:::
