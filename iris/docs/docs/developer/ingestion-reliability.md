---
title: Ingestion Reliability
---

# Ingestion Reliability

A lecture unit is only useful to the chat and to global search if the Iris collections hold exactly its current content: every page, the current attachment version, one transcript, and nothing left over from an earlier run. This page is the source of truth for how Iris guarantees that: how it receives work, how a run writes and verifies its result, and what it reports so that Artemis can find and repair what is missing. What a run extracts from a PDF or a video is described in the [RAG pipeline](./rag-pipeline.md); how a running job is superseded or cancelled is described in [Ingestion jobs](./ingestion-jobs.md).

Artemis owns the other half of the loop: the job queue, the retry budgets, and the reconciliation walk that compares the census with its database. Its configuration is documented in the [Artemis administration guide](https://docs.artemis.cit.tum.de/admin/artemis-intelligence).

## Architecture overview

```text
Dispatch:    Iris worker -> claim from Artemis queue -> LectureIngestionUpdatePipeline -> heartbeat while it runs
Write:       embed every chunk -> write new generation -> verify -> purge everything else -> audit -> FINISHED
Repair:      Artemis reconciliation -> GET ingestion census -> re-queue units that differ from the database
```

Each of the three steps can fail on its own. A worker can die mid-run, a write can be interrupted, and a callback can be lost on the way back. The design assumes that every one of these happens, and makes each recoverable by the next step rather than by the step itself.

## Pull-based worker

Lecture ingestion is a queued batch workload, so Iris consumes it like a build agent consumes builds: `IngestionWorker` (`ingestion/worker.py`) claims jobs from Artemis when it has free capacity, instead of Artemis pushing them. Interactive features such as the chat stay on push and callback. Artemis holds the whole queue in its database, with row locks for claims, priorities and retry budgets; Iris keeps no durable state.

### Upstream discovery

Iris is not configured with the Artemis instances it serves. Every Artemis already sends an authenticated health check, and includes its own base URL in the `X-Artemis-Base-Url` header. The health endpoint registers that URL, together with the token of the request, as an upstream. An upstream that stops announcing itself expires once it owns no running jobs. After a restart, Iris relearns its upstreams within one health-check interval; until then, new jobs simply wait in the Artemis queue. Current Artemis no longer pushes lecture jobs; `POST /api/v1/webhooks/lectures/ingest` remains for callers that still do, and runs the same pipeline.

`ingestion_worker.allowed_upstream_hosts` restricts the hosts Iris accepts as upstreams. Only well-formed http(s) URLs are accepted, and the worker does not follow redirects, so an accepted upstream cannot redirect it to a host that the list would have rejected.

### Claim and lease

The worker runs two loops against every fresh upstream, both on `POST {artemis_base_url}/api/iris/internal/ingestion/worker/...`:

| Loop      | Request                                     | Response                  | Interval                                   |
| --------- | ------------------------------------------- | ------------------------- | ------------------------------------------ |
| Claim     | `claim` with `bootId` and `maxJobs`         | The jobs Artemis assigned | `poll_interval_seconds` (default 2 s)      |
| Heartbeat | `heartbeat` with the tokens of running jobs | `revokedJobTokens`        | `heartbeat_interval_seconds` (default 5 s) |

`maxJobs` is the number of free slots (`ingestion_worker.capacity`, default 2), and the worker starts at most that many jobs, even if Artemis returns more. Every claimed job is reserved before the first one starts, so a slow start cannot lead to over-claiming.

The heartbeat renews the lease of every running job. It is a timer, decoupled from the progress of the pipeline, so the lease never has to be sized to the unpredictable duration of a transcription or a vision call. When a worker dies, its leases stop being renewed, and Artemis reclaims the job within seconds. When Artemis has reassigned a job in the meantime, the heartbeat response names it in `revokedJobTokens`, and the worker sets the run's cancellation event; the run stops at its next checkpoint, as described in [Ingestion jobs](./ingestion-jobs.md). `bootId` lets Artemis recognize a restarted Iris, whose previous runs are gone.

## Writing a generation

Every run writes its rows under its own `ingestion_run_id`, called a generation. `LectureIngestionPipeline` replaces a unit's page chunks in the following sequence:

1. embed every chunk of the new generation, before anything is written and outside the shared write lock;
2. write the new generation under client-assigned ids and verify that the store holds it;
3. purge every row of the unit that does not belong to this generation: the previous generation, rows written before generations existed, leftovers of crashed runs, and rows left behind by store corruption; and
4. check that exactly one generation remains.

The order is the point. All fallible LLM work is done before the first write, and the old content is only removed once the new content is verified. A crash between the write and the purge leaves both generations in the store for a moment, never an empty unit; the next run's purge, or the skip check below, which rejects mixed generations, converges the unit. Transcriptions follow the same pattern.

If more than one generation is still visible after the purge, `convergence_max_escalations` (default `0`) decides whether the run deletes every row of the unit and rewrites its generation from scratch. With the default, the run fails with its verified generation intact, and the reconciliation retries it.

### Ghost rows

An interrupted write can leave a row that a Weaviate scan still returns, but that has no record in the object store: `fetch_object_by_id` returns nothing for it, retrieval never surfaces it, and no delete can remove it. Counting generations from a raw scan would count such a ghost, so a unit with one real generation would look dirty forever, and every re-ingestion would fail to clean it.

`batch_verify.py` therefore confirms each generation against the object store: a generation is real only if at least one of its rows can be fetched by id. Convergence, the audit and the census all count confirmed generations and rows only.

### Skipping unchanged content

Before it does any work, the pipeline checks whether the stored chunks are already current and complete. It skips the PDF only if every condition holds:

- the stored attachment version and requested language match the request;
- the unit holds exactly one confirmed generation;
- the page coverage is complete; and
- the chunk count matches the manifest recorded by the previous run.

A crash-damaged unit therefore never passes as current, and an unchanged one is not re-ingested on every reconciliation.

## Verifying a run

### Audit

`FINISHED` is a verified claim. Before the terminal callback, `pipeline/ingestion_audit.py` reads back what Weaviate holds for the unit and compares it with a manifest derived only from the request: the PDF's page count, the slide numbers of the transcript, the attachment version, and the content fingerprint that Artemis computed for the unit. A missing page, a chunk from an older attachment version, a transcript that should or should not exist, a gap in the segments, or a duplicated unit row fails the run instead of certifying a partial unit.

The audit reads identity properties only, never content, and makes no LLM calls. It confirms the rows it reads against the object store, so its cost grows with the size of the unit.

### Quality

`pipeline/ingestion_quality.py` scores the page chunks of a run without an LLM call. The score is the fraction of pages that are neither empty, thin (fewer than 80 characters) nor garbled (less than half letters and digits); flags name the failing pages. The verdict is deterministic on purpose: it feeds a control loop, and a verdict that changed between identical runs would make that loop oscillate.

The score and the flags are stored on the unit row together with `INGESTION_PIPELINE_VERSION` (`common/ingestion_version.py`). Artemis re-queues a low-quality unit at most once per pipeline version: bump the version when a change to prompts, models, chunking or extraction can produce a better result for unchanged content. If a re-run scores worse than the stored generation, and the stored generation passes the same structural checks as the skip check, the run keeps the stored generation.

## Census

The census tells Artemis what the index actually holds, so that it can compare that with its database instead of trusting callbacks:

```text
GET /api/v1/courses/{course_id}/ingestion-census?base_url={artemis_base_url}
```

It returns one `IngestionCensusUnitDTO` per lecture unit (`domain/ingestion/ingestion_census_dto.py`). A unit appears as soon as any collection holds rows for it, so content whose unit row is gone is still reported.

| Field                                               | Meaning                                                                                       |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `contentFingerprint`                                | The fingerprint stamped on the unit row; Artemis re-ingests a unit whose fingerprint differs. |
| `generationCount`                                   | Confirmed generations among the page chunks. More than one means stale rows coexist.          |
| `chunkCount`, `expectedChunkCount`                  | Confirmed page chunks, and the count the last run recorded.                                   |
| `chunkPageMin`, `chunkPageMax`, `missingPageCount`  | Page coverage. A complete unit covers its pages without holes.                                |
| `chunkVersionMin`, `chunkVersionMax`                | Attachment versions among the chunks.                                                         |
| `nullDisplayCount`                                  | Chunks whose printed slide number was never resolved.                                         |
| `transcriptionCount`, `segmentCount`                | Transcript and segment rows.                                                                  |
| `pipelineVersion`, `qualityScore`, `courseLanguage` | What the last run stamped on the unit row.                                                    |
| `truncated`                                         | The unit's fetch hit the row cap, so its counts may be too low.                               |

The response also carries `currentPipelineVersion` and a course-level `truncated` flag. When the course-wide scan hits its cap, a unit whose row was not read looks exactly like a unit without a row, so a truncated response must not be treated as exhaustive. Confirming rows against the object store runs with `lecture_ingestion.census_confirm_concurrency` (default 16) parallel reads.

## Configuration

| Setting                                         | Default | Effect                                                                                                       |
| ----------------------------------------------- | ------- | ------------------------------------------------------------------------------------------------------------ |
| `ingestion_worker.enabled`                      | `true`  | Claims jobs from announced upstreams. Off, this process ingests no lectures; jobs wait in the Artemis queue. |
| `ingestion_worker.capacity`                     | `2`     | Jobs this process runs at the same time.                                                                     |
| `ingestion_worker.poll_interval_seconds`        | `2.0`   | Interval between claims.                                                                                     |
| `ingestion_worker.heartbeat_interval_seconds`   | `5.0`   | Interval between lease renewals.                                                                             |
| `ingestion_worker.heartbeat_timeout_seconds`    | `10.0`  | Request timeout of a heartbeat, kept well below the Artemis lease.                                           |
| `ingestion_worker.allowed_upstream_hosts`       | `[]`    | Hosts accepted as upstreams; empty accepts every announced host.                                             |
| `lecture_ingestion.convergence_max_escalations` | `0`     | Full rewrites a run may attempt when generations do not converge.                                            |
| `lecture_ingestion.census_confirm_concurrency`  | `16`    | Parallel object-store reads of the census.                                                                   |

Switching the worker off stops ingestion on the Iris side, but not the queue: Artemis keeps queueing new and reconciled units, and every Iris whose worker is on claims them. To stop ingestion for an Artemis instance, also switch off its reconciliation; see the [Artemis administration guide](https://docs.artemis.cit.tum.de/admin/artemis-intelligence).

## Boundaries

- **The queue and the retry budgets** belong to Artemis. Iris never decides that a unit needs ingesting; it runs what it claims and reports what it holds.
- **The fingerprint** is computed by Artemis from the unit's content. Iris only stores and compares it.
- **FAQs** are not ingested by the worker. They have their own census, `GET /api/v1/faq-census`, which Artemis uses to reconcile them.
- **The Artemis search index** is a separate collection with its own repair loop in Artemis; see [Global search](./global-search.md).
