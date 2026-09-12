# Batch processing

Many requests, nobody waiting. Logos serves the OpenAI Batch API for that, and
runs it in one of two places:

- **At the provider**, when a provider the key may use offers a Batch API that
  serves every model the file names. That is where the provider's batch rate
  applies (roughly half the standard price), so it is always preferred.
- **In Logos**, otherwise. A model served by a worker node has no upstream Batch
  API at all, and a cloud model can be missing from its provider's batch
  offering — Azure adds models to Batch long after Standard, so the newest ones
  cannot be batched there for months. Logos then schedules the file's requests
  itself at the **lowest queue priority**: they fill whatever capacity
  interactive traffic is not using and finish as fast as that capacity allows.

Both paths speak the same API, so a script uploads, polls, and chains the next
batch onto the last without knowing or caring which one it got.

- [What Logos serves](#what-logos-serves)
- [Using it](#using-it)
- [Where a batch runs](#where-a-batch-runs)
- [What Logos enforces](#what-logos-enforces)
- [Billing](#billing)
- [Azure specifics](#azure-specifics)
- [The batch page in the UI](#the-batch-page-in-the-ui)
- [Limits and what is deliberately not supported](#limits-and-what-is-deliberately-not-supported)
- [Alternative: the async job API](#alternative-the-async-job-api)

## What Logos serves

| Operation | Route |
| --- | --- |
| Upload a batch input file | `POST /v1/files` (`purpose=batch`) |
| List your files | `GET /v1/files` |
| Retrieve a file object | `GET /v1/files/{file_id}` |
| Download file content | `GET /v1/files/{file_id}/content` |
| Delete a file | `DELETE /v1/files/{file_id}` |
| Create a batch | `POST /v1/batches` |
| List your batches | `GET /v1/batches` |
| Retrieve a batch | `GET /v1/batches/{batch_id}` |
| Cancel a batch | `POST /v1/batches/{batch_id}/cancel` |

Every route is also served under the `/openai/`, `/jobs/v1/` and
`/jobs/openai/` mirrors. The `/v2/` (Cohere) surface has no batch routes.

Responses are the provider's own objects and errors, unchanged, so the OpenAI
SDKs work against Logos without modification.

## Using it

```python
from openai import OpenAI

client = OpenAI(base_url="https://logos.ase.cit.tum.de/v1", api_key=LOGOS_KEY)

# One JSON object per line. `model` is the Logos model name, exactly as in a
# normal request — Logos translates it to whatever the provider calls it.
batch_input = client.files.create(file=open("requests.jsonl", "rb"), purpose="batch")

batch = client.batches.create(
    input_file_id=batch_input.id,
    endpoint="/v1/chat/completions",
    completion_window="24h",
)

# Poll until terminal, then read the results.
batch = client.batches.retrieve(batch.id)
results = client.files.content(batch.output_file_id)
```

A request line looks like this:

```json
{"custom_id": "q-1", "method": "POST", "url": "/v1/chat/completions",
 "body": {"model": "gpt-4.1", "messages": [{"role": "user", "content": "…"}]}}
```

A polling script is the normal client:

```python
import time

while batch.status not in ("completed", "failed", "expired", "cancelled"):
    time.sleep(120)
    batch = client.batches.retrieve(batch.id)
```

## Where a batch runs

The decision is made when the **input file** is uploaded, because what the file
asks for is what decides where it can go. The batch inherits it.

1. A batch body carries no `model`, so the provider cannot be routed to the way
   an inference request is. Logos takes the key's provider permissions instead:
   if exactly one provider the key may use serves a Batch API, that is the
   candidate. With several, name one in the `X-Logos-Provider` header (name or
   id); without it the request is refused with `multiple_batch_providers` rather
   than guessed.
2. The candidate is used only if it serves **every** model the file names — a
   provider cannot run a request for a model it does not host, and a batch is
   one job at one place.
3. Otherwise Logos runs the batch itself.

Whether a provider serves a Batch API is probed rather than configured — a
self-hosted OpenAI-shaped inference endpoint answers `/chat/completions` and
nothing else, and a hand-set flag would go stale. The result is cached for
`LOGOS_BATCH_CAPABILITY_TTL_HOURS` (default 24).

Serving a Batch API and batching a *given model* are two different things:
on Azure each model needs its own Global-Batch deployment, and a model that
only exists as a Standard deployment cannot be batched there even though the
resource serves the Batch API. The provider does not publish its batch model
list, so Logos learns this from its own refusals: when it refuses a batch
creation (or a batch finishes failed) with a model-availability error, the
models of that input file are recorded as not batch-eligible on that provider
and route to Logos execution from the next file on. The record expires after
`LOGOS_BATCH_MODEL_ELIGIBILITY_TTL_DAYS` (default 90), so a model the provider
adds to Batch later is picked up automatically; the cost of a stale record is
one more refused batch.

`X-Logos-Batch-Execution` overrides the choice:

| Value | Effect |
| --- | --- |
| `auto` (default) | Forward when possible, run here otherwise. |
| `logos` | Run here even when a provider could have taken it. |
| `provider` | Fail with `501`/`model_not_available_for_batch` rather than run here. |

The batch object carries `logos_execution` (`"provider"` or `"logos"`) so a
client that cares whether it got the discounted rate can tell.

**What a Logos-run batch does.** Each request line is scheduled through the
ordinary pipeline at queue priority `LOW`, `LOGOS_BATCH_LOCAL_CONCURRENCY`
(default 8) at a time. Every line is an ordinary request — authorised, routed,
logged and metered exactly like one a client sent — so the batch shows up in
statistics and budgets request by request as it runs. Input and result files
are held by Logos (in the database, so the UI can serve them and a redeploy
does not lose them). Progress is published as it goes, so
`request_counts.completed` moves while the batch runs; cancelling stops it
before the next line rather than killing the one in flight. A batch left
running by a restart is picked up again on the next pass of the runner
(`LOGOS_BATCH_LOCAL_POLL_INTERVAL_S`, default 15 s), which is also what starts
one submitted while the process was down.

## What Logos enforces

Being allowed to use a provider does not authorise everything that provider can
do, so the passthrough is not blind:

- **Model permissions per request line.** Each line of the input file names its
  own model. Every line is checked against the key's model permissions on the
  target provider before the file is accepted; a line naming a model the key may
  not use fails the upload with `403 model_not_permitted` and the line number.
  Only `/v1/chat/completions`, `/v1/responses` and `/v1/embeddings` may be
  addressed.
- **Ownership.** File and batch ids are used for hours after the call that
  minted them, with a provider credential shared by every key allowed to use
  that provider. Logos records each id with its owner — the creating team, or
  the creating user and key for a team-less personal key; a lifecycle call for
  an id someone else owns is answered `404`, exactly like an id that never
  existed. `GET /v1/batches` and `GET /v1/files` are answered from Logos' own
  record rather than forwarded, so they show the caller team's objects and
  nobody else's — and cover the batches Logos ran itself, which no provider
  knows about. They return one page (`has_more` is always `false`); the
  provider's paging cursors describe its own unfiltered list and would mislead
  a client walking ours.
- **Budget.** Creating a batch is refused with `402` when the key or its team is
  already over its monthly budget. The batch's own cost is settled when it
  finishes (see below), so it is not known up front.

Uploads are capped at `LOGOS_MAX_BATCH_FILE_BYTES` (default 50 MiB) and
`LOGOS_MAX_BATCH_REQUESTS` lines (default 50 000, the provider's own ceiling).
Only `purpose="batch"` is accepted: Logos serves the Files API as the Batch
API's transport, not as a general-purpose object store.

## Billing

A **Logos-run** batch needs no special handling: its lines are ordinary
requests, so they are metered as they run, at the ordinary rate (the provider
never saw a batch, so there is no batch rate to apply — and for a worker-node
model there is nothing to pay in the first place).

A **forwarded** batch is metered when it finishes. When it reaches a terminal
state — either because the client polled it or because the background
reconciler found it (`LOGOS_BATCH_RECONCILE_INTERVAL_S`, default 300 s) — Logos
reads its output file once and books **one usage row per result line**, with
the owning key, team, model and provider. Batch spend therefore appears in the
same budget, statistics and export surfaces as everything else.

Those rows carry `service_tier = 'batch'`, which makes the price lookup use the
provider's batch rate (imported from the model catalogue's `*_batches` prices).
A model with no published batch rate falls back to its standard rate, so an
unpriced batch is over- rather than under-charged.

Settlement is latched in the database, so a batch is metered exactly once even
when the client's poll and the reconciler reach it simultaneously; a settlement
that fails (an unreadable output file, say) releases the latch and is retried.

Note that Logos books what the *result rows* report. The provider is the source
of truth for the invoice; these rows are Logos' attribution of it.

## Azure specifics

Azure serves Batch at the resource level (`{resource}/openai/v1/batches`), not
under a deployment, so Logos addresses it there rather than through the
deployment URLs it uses for inference. The dated data-plane spelling
(`{resource}/openai/batches?api-version=…`) is reachable by setting
`LOGOS_AZURE_BATCH_API_VERSION`; note that `2024-02-01`, the version some docs
still name, does **not** serve these routes.

Azure identifies models by *deployment*, so the `model` field of every request
line is rewritten from the Logos model name to the deployment id on upload, and
mapped back when the results are metered. Clients keep using Logos model names.

**Two operational prerequisites, both outside Logos:**

1. **A Global-Batch (or Data Zone Batch) deployment must exist** on the Azure
   resource for each model you want to batch. Batch is a separate deployment
   type with its own quota; a Standard deployment of the same model cannot run
   batch jobs.
2. **The model must be offered for batch at all.** Azure adds models to Batch
   later than to Standard, with no published parity timeline. As of
   September 2026 the Global Batch and Data Zone Batch availability tables list
   `gpt-4.1` (and mini/nano), `gpt-4o` (and mini), `gpt-5`, `gpt-5.1`, `gpt-5.4`,
   `gpt-5.4-mini`, `o3`, `o3-mini` and `o4-mini` — the GPT-5.5 and GPT-5.6
   families (`gpt-5.6-luna`, `-terra`, `-sol`) are **not** available for batch,
   so there is no batch discount for them on Azure today. They do have one on
   OpenAI direct.

   A batch naming one of those models is not refused: Logos runs it here
   instead, at the standard rate but with the same API. The day Azure adds the
   model to Batch, the same file starts taking the discounted path with no
   change on the client side.

Run-time: `completion_window` must be `"24h"`, and that is a **service goal,
not a deadline**. Azure aims to finish within 24 hours but does not expire jobs
that take longer — they keep running until they complete or you cancel them,
and cancelling bills the work already done. A job the service could not finish
inside the window is reported as `expired`.

Sources: [Azure OpenAI global batch](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/batch),
[model region availability](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability),
[pricing](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).

## The batch page in the UI

**Batches** under *Personal* does the same three things without a script: pick
one of your API keys, upload a `.jsonl`, and watch the list. A running batch
shows its progress, a finished one offers its results as a download, and an
unfinished one can be cancelled. The page refreshes itself every 30 seconds
while something is still moving.

It is a forward to the same API: the webservice calls the orchestrator's Batch
API as the key you selected, so the per-line permission check, the ownership
rule and the budget guard are exactly the ones a script gets. The browser never
sees the key value — it names a key by id, and the webservice refuses one that
is not yours.

## Limits and what is deliberately not supported

- **No cross-provider batches.** One batch runs in one place. A file whose
  models are not all on one Batch-capable provider runs in Logos rather than
  being split.
- **A Logos-run batch gets no discount.** There is none to get: the requests are
  ordinary requests. It buys the API and the low-priority scheduling, not a
  lower rate.
- **No rate-limit accounting.** A batch consumes the provider's separate
  enqueued-token quota, which Logos does not model. An oversized batch is
  refused by the provider, and that error is passed through.
- **Derived billable quantities** (image counts, search queries) are not
  reconstructed from batch results; token usage is taken from the result rows.
- **`purpose` values other than `batch`** are refused, so the Files API cannot
  be used as general storage through Logos.

## Alternative: the async job API

For work that is merely latency-tolerant rather than large, the async job API
decouples the client from the wait without the Batch API's machinery:
`POST /jobs/v1/chat/completions` returns `202` with a `Location` header and
`GET /jobs/{job_id}` polls for the result. Those jobs run the ordinary
pipeline and are billed at the **standard** per-token rate — the batch discount
comes from the provider's batch endpoint, which only the routes above use.
