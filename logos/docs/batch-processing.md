# Batch processing

Use batch processing when you send many requests and nobody waits for the
answers. Logos serves the OpenAI Batch API for this purpose. Logos runs a batch
in one of two places:

- **At the provider.** This applies if a provider that the key can use offers a
  Batch API that serves every model the file names. The provider's batch rate
  applies there (about half the standard price). Logos always prefers this place.
- **In Logos.** This applies in all other cases. A model on a worker node has no
  upstream Batch API. A cloud model can be missing from the batch offer of its
  provider. For example, Azure adds models to Batch long after Standard, so the
  newest models cannot be batched there for months. In this case, Logos schedules
  the requests of the file itself at the **lowest queue priority**. The requests
  use the capacity that interactive traffic does not use. They finish as fast as
  that capacity allows.

Both places use the same API. A script uploads a file, polls, and starts the
next batch. The script does not need to know which place Logos used.

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

Logos also serves every route under the `/openai/`, `/jobs/v1/` and
`/jobs/openai/` mirrors. The `/v2/` (Cohere) surface has no batch routes.

Logos returns the objects and errors of the provider without change. The OpenAI
SDKs therefore work with Logos without modification.

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

This is an example of a request line:

```json
{"custom_id": "q-1", "method": "POST", "url": "/v1/chat/completions",
 "body": {"model": "gpt-4.1", "messages": [{"role": "user", "content": "…"}]}}
```

This is an example of a polling script:

```python
import time

while batch.status not in ("completed", "failed", "expired", "cancelled"):
    time.sleep(120)
    batch = client.batches.retrieve(batch.id)
```

## Where a batch runs

Logos decides where a batch runs when you upload the **input file**. The file
shows which models the batch needs, and this decides where the batch can go. The
batch uses the same place as its input file.

1. A batch body has no `model`. Logos cannot select the provider in the way it
   does for an inference request. Logos uses the provider permissions of the key
   instead. If exactly one provider that the key can use serves a Batch API, then
   this provider is the candidate. If the key can use more than one such
   provider, then name one in the `X-Logos-Provider` header (name or id). Without
   the header, Logos refuses the request with `multiple_batch_providers`. Logos
   does not guess.
2. Logos uses the candidate only if it serves **every** model that the file
   names. A provider cannot run a request for a model that it does not host, and
   a batch is one job in one place.
3. In all other cases, Logos runs the batch itself.

Logos probes a provider to find out if it serves a Batch API. A flag that you
set by hand would become wrong with time. For example, a self-hosted
OpenAI-shaped inference endpoint answers `/chat/completions` and no other
route. Logos caches the result for `LOGOS_BATCH_CAPABILITY_TTL_HOURS` (default
24).

A provider that serves a Batch API does not necessarily batch a *given model*.
On Azure, each model needs its own Global-Batch deployment. A model that exists
only as a Standard deployment cannot be batched there, although the resource
serves the Batch API. The provider does not publish its list of batch models.
Logos learns the list from its own refusals. A refusal happens when Logos
refuses a batch creation, or when a batch finishes as failed, with a
model-availability error. Then Logos records the models of that input file as
not batch-eligible on that provider. Logos runs these models itself from the next
file on. The record expires after `LOGOS_BATCH_MODEL_ELIGIBILITY_TTL_DAYS`
(default 90). Logos therefore finds a model that the provider adds to Batch
later. The cost of an old record is one more refused batch.

The header `X-Logos-Batch-Execution` overrides the choice:

| Value | Effect |
| --- | --- |
| `auto` (default) | Forward when possible, run here otherwise. |
| `logos` | Run here even when a provider could have taken it. |
| `provider` | Fail with `501`/`model_not_available_for_batch` rather than run here. |

The batch object has the field `logos_execution` (`"provider"` or `"logos"`). A
client can use it to find out if the batch got the discounted rate.

**What a Logos-run batch does.** Logos schedules each request line through the
ordinary pipeline at queue priority `LOW`. Logos runs `LOGOS_BATCH_LOCAL_CONCURRENCY`
(default 8) lines at the same time. Each line is an ordinary request. Logos
authorizes, routes, logs and meters it in the same way as a request from a
client. The batch therefore shows in the statistics and budgets request by
request while it runs.

Logos holds the input files and result files in the
database. The UI can serve them, and a redeploy does not delete them. Logos
publishes the progress while the batch runs, so `request_counts.completed`
changes during the run.
A cancel stops the batch before the next line. It does
not stop the line that is in progress. A restart can leave a batch in the
running state. The runner continues this batch in its next pass
(`LOGOS_BATCH_LOCAL_POLL_INTERVAL_S`, default 15 s). The same pass also starts a
batch that a client submitted while the process was down.

## What Logos enforces

Permission to use a provider does not give permission for everything that the
provider can do. Logos therefore does not pass requests through without checks:

- **Model permissions per request line.** Each line of the input file names its
  own model. Before Logos accepts the file, it checks every line against the
  model permissions of the key on the target provider. If a line names a model
  that the key cannot use, then the upload fails with `403 model_not_permitted`
  and the line number. A line can address only `/v1/chat/completions`,
  `/v1/responses` and `/v1/embeddings`.
- **Ownership.** File ids and batch ids stay in use for hours after the call that
  created them. Every key that can use the provider shares one provider
  credential. Logos therefore records each id with its owner. The owner is the
  creating team. For a personal key without a team, the owner is the creating
  user and key. If a lifecycle call uses an id that another owner has, then
  Logos answers `404`, the same as for an id that never existed. Logos answers
  `GET /v1/batches` and `GET /v1/files` from its own record and does not forward
  them. The answer shows the objects of the team of the caller and no other
  objects. It also includes the batches that Logos ran itself, which no provider
  knows. The answer is one page, and `has_more` is always `false`. The paging
  cursors of the provider describe its own unfiltered list. They would mislead a
  client that walks the list of Logos.
- **Budget.** If the key or its team is already over its monthly budget, then
  Logos refuses the creation of a batch with `402`. Logos settles the cost of
  the batch when the batch finishes (see below). The cost is not known before.

Logos limits an upload to `LOGOS_MAX_BATCH_FILE_BYTES` (default 50 MiB) and to
`LOGOS_MAX_BATCH_REQUESTS` lines (default 50 000, the limit of the provider).
Logos accepts only `purpose="batch"`. Logos serves the Files API as the
transport of the Batch API. It is not a general-purpose object store.

## Billing

A **Logos-run** batch needs no special handling. Its lines are ordinary
requests, and Logos meters them while they run, at the ordinary rate. The
provider never saw a batch, so no batch rate applies. For a model on a worker
node, there is no cost to pay.

Logos meters a **forwarded** batch when it finishes. The batch reaches a
terminal state when the client polls it, or when the background reconciler finds
it (`LOGOS_BATCH_RECONCILE_INTERVAL_S`, default 300 s). Then Logos reads the
output file once. Logos books **one usage row for each result line**, with the
owning key, team, model and provider. The batch spend therefore shows in the
same budget, statistics and export surfaces as all other spend.

These rows have `service_tier = 'batch'`. This makes the price lookup use the
batch rate of the provider. Logos imports this rate from the `*_batches` prices
of the model catalogue. If a model has no published batch rate, then Logos uses
its standard rate. An unpriced batch is therefore over-charged and not
under-charged.

Logos latches the settlement in the database. A batch is metered exactly once,
also when the poll of the client and the reconciler reach it at the same time.
If a settlement fails (for example, the output file is unreadable), then Logos
releases the latch and tries again.

Note: Logos books what the *result rows* report. The provider is the source of
truth for the invoice. These rows are the attribution of the invoice by Logos.

## Azure specifics

Azure serves Batch at the resource level (`{resource}/openai/v1/batches`) and
not under a deployment. Logos therefore addresses Batch there. For inference,
Logos uses the deployment URLs. To use the dated data-plane format
(`{resource}/openai/batches?api-version=…`), set `LOGOS_AZURE_BATCH_API_VERSION`.
Note: the version `2024-02-01`, which some documents still name, does **not**
serve these routes.

Azure identifies models by *deployment*. On upload, Logos changes the `model`
field of each request line from the Logos model name to the deployment id. When
Logos meters the results, it changes the id back. Clients continue to use Logos
model names.

**Two operational prerequisites exist. Both are outside Logos:**

1. **A Global-Batch (or Data Zone Batch) deployment must exist** on the Azure
   resource for each model that you want to batch. Batch is a separate
   deployment type with its own quota. A Standard deployment of the same model
   cannot run batch jobs.
2. **Azure must offer the model for batch.** Azure adds models to Batch later
   than to Standard, and it publishes no date for equal availability. In
   September 2026, the Global Batch and Data Zone Batch availability tables list
   `gpt-4.1` (and mini/nano), `gpt-4o` (and mini), `gpt-5`, `gpt-5.1`, `gpt-5.4`,
   `gpt-5.4-mini`, `o3`, `o3-mini` and `o4-mini`. The GPT-5.5 and GPT-5.6
   families (`gpt-5.6-luna`, `-terra`, `-sol`) are **not** available for batch.
   There is no batch discount for them on Azure today. They have a discount on
   OpenAI direct.

   Logos does not refuse a batch that names one of these models. Logos runs it
   itself at the standard rate with the same API. When Azure adds the model to
   Batch, the same file uses the discounted path. The client does not change.

Run time: `completion_window` must be `"24h"`. This is a **service goal and not
a deadline**. Azure tries to finish in 24 hours, but it does not expire jobs that
take longer. These jobs continue until they complete or you cancel them. A
cancel bills the work that is already done. If the service cannot finish a job
in the window, then it reports the job as `expired`.

Sources: [Azure OpenAI global batch](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/batch),
[model region availability](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability),
[pricing](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).

## The batch page in the UI

**Batches** under *Management* does the same three things without a script. Select
one of your API keys, upload a `.jsonl` file, and look at the list. A running
batch shows its progress. A finished batch offers its results as a download. You
can cancel a batch that is not finished. The page refreshes every 30 seconds
while a batch is in progress.

The page is an admin function. Only app admins and logos admins see the menu
item, and the endpoints behind it refuse all other users. Script use does not
change. A script uses the Batch API directly and not the page.

The page forwards to the same API. The webservice calls the Batch API of the
orchestrator with the key that you selected. The per-line permission check, the
ownership rule and the budget guard are therefore the same as for a script. The
browser never sees the value of the key. It names a key by id, and the webservice
refuses a key that is not yours.

## Limits and what is deliberately not supported

- **No cross-provider batches.** One batch runs in one place. If the models of a
  file are not all on one provider that has a Batch API, then Logos runs the
  file itself. Logos does not split it.
- **A Logos-run batch gets no discount.** No discount exists, because the
  requests are ordinary requests. The batch gives the API and the low-priority
  scheduling, but not a lower rate.
- **No rate-limit accounting.** A batch uses the separate enqueued-token quota of
  the provider. Logos does not model this quota. The provider refuses an
  oversized batch, and Logos passes this error through.
- **Derived billable quantities** (image counts, search queries) are not
  reconstructed from batch results. Logos takes the token usage from the result
  rows.
- **`purpose` values other than `batch`** are refused. You cannot use the Files
  API as general storage through Logos.

## Alternative: the async job API

Use the async job API for work that can wait but is not large. It frees the
client from the wait and does not need the machinery of the Batch API.
`POST /jobs/v1/chat/completions` returns `202` with a `Location` header.
`GET /jobs/{job_id}` polls for the result. These jobs run the ordinary pipeline.
Logos bills them at the **standard** per-token rate. The batch discount comes
from the batch endpoint of the provider, and only the routes above use it.
