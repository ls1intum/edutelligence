# Course Memory — Artemis Integration Spec

Hand-off contract for implementing the **Artemis (Java / Spring Boot) side** of the
Course Memory feature. The **Pyris side is already implemented** (Weaviate collection,
ingestion pipeline, retrieval tool wired into the autonomous tutor, webhook endpoint,
config). This document is the exact contract Artemis must satisfy to make it work.

## What Artemis must build

1. **Ingestion triggers** that POST resolved/verified threads to a new Pyris webhook
   (Trigger A: tutor verification; Trigger B: thread resolved).
2. **A status-callback controller** that receives ingestion progress from Pyris.
3. **DTOs** matching the JSON contract below.
4. **No new work for retrieval** — it happens inside the autonomous-tutor pipeline that
   Artemis already invokes. See [Retrieval](#retrieval-no-new-artemis-work).

Reuse the **existing Pyris integration plumbing** (the same service that already calls
`/api/v1/webhooks/faqs/ingest` and `/api/v1/webhooks/lectures/ingest`, e.g.
`PyrisConnectorService`). The auth, base URL, variant/selection handling, and the
status-callback controller pattern are all identical to **FAQ ingestion** — mirror it.

---

## 1. Authentication

Same model as existing FAQ/lecture ingestion — **do not invent a new scheme**:

- **Artemis → Pyris (request):** Pyris validates the raw `Authorization` header against
  its configured `api_keys` token. Send exactly what the existing FAQ/lecture webhook
  calls send (the configured Pyris API token).
- **Pyris → Artemis (status callback):** Pyris sends
  `Authorization: Bearer <runId>` where `<runId>` is the `authenticationToken` you put
  in the request `settings`. Validate it the same way the FAQ ingestion status endpoint
  does.

---

## 2. Outbound: ingestion request (Artemis → Pyris)

**Endpoint:** `POST {pyrisBaseUrl}/api/v1/webhooks/course-memory/ingest`
**Response:** `202 Accepted` immediately; processing runs async on Pyris. A `400` means
the requested variant/models aren't available on Pyris — handle gracefully (log/skip).

### JSON body (field names are the wire aliases — exact casing matters)

```jsonc
{
  "settings": {
    "authenticationToken": "<run id; echoed back as Bearer on the status callback>",
    "artemisBaseUrl": "https://artemis.example.com",
    "selection": "CLOUD_AI", // or "LOCAL_AI"
    "variant": "default",
  },

  "courseId": 1, // int, REQUIRED — scopes storage + retrieval
  "conversationId": "12345", // string, REQUIRED — originating thread id (backlink)
  "messageId": "67890", // string, REQUIRED — answer message id; UPSERT KEY
  "source": "THREAD_RESOLVED", // enum, REQUIRED — see below
  "isPublicChannel": true, // bool — MUST be true; non-public is skipped by Pyris

  "thread": [
    // ordered oldest→newest; full thread
    {
      "id": "67888",
      "authorRole": "student",
      "content": "How do I submit?",
      "createdAt": "2026-06-21T09:58:00Z",
      "isIrisDraft": false,
    },
    {
      "id": "67890",
      "authorRole": "tutor",
      "content": "Push to your repo before the deadline.",
      "createdAt": "2026-06-21T10:00:00Z",
      "isIrisDraft": false,
    },
  ],

  "verifiedBy": "tutor-42", // optional string — who verified (Trigger A)
  "verifiedAt": "2026-06-21T10:00:00Z", // optional ISO-8601 string
  "existingAnswer": null, // optional string — see IRIS_CORRECTED below
}
```

### Field semantics / invariants

| Field                  | Type       | Notes                                                                                                                                                                                                                                            |
| ---------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `courseId`             | int        | Required. Scopes every search; entries are never returned cross-course.                                                                                                                                                                          |
| `conversationId`       | **string** | Artemis ids are `Long` — **stringify them**. Stored for backlinking.                                                                                                                                                                             |
| `messageId`            | **string** | **Stringify.** This is the **dedup/upsert key**: Pyris maps `(courseId, messageId)` to a deterministic UUID. Use the **stable id of the answer message**, not a per-event id. Re-sending the same `messageId` **overwrites** the existing entry. |
| `source`               | enum       | One of `IRIS_AUTO`, `TUTOR_WRITTEN`, `IRIS_CORRECTED`, `THREAD_RESOLVED`.                                                                                                                                                                        |
| `isPublicChannel`      | bool       | Send `true` only for public channels. Pyris skips ingestion if `false` (defense in depth — but **Artemis must only fire for public channels**, req. 5).                                                                                          |
| `thread`               | array      | Full thread, **ordered oldest→newest**. Pyris truncates to the last `context_message_limit` (default 20) messages, but send the thread. The LLM extractor uses it to derive the canonical question + verified answer.                            |
| `thread[].authorRole`  | string     | Use `"student"`, `"tutor"`, or `"iris"`. The extractor relies on this to identify the verified answer (prefers a tutor message, or an Iris message approved by a tutor).                                                                         |
| `thread[].isIrisDraft` | bool       | Mark the Iris-generated draft message `true` so the extractor knows it was AI-authored.                                                                                                                                                          |
| `existingAnswer`       | string     | When set **and** `source = IRIS_CORRECTED`, Pyris uses this text as the answer **verbatim** (skips re-extracting the answer; still derives the canonical question from the thread). Use it to pass the tutor-edited answer.                      |

### `source` value → which trigger

- `THREAD_RESOLVED` — Trigger B (thread marked resolved, never went through verification).
- `IRIS_AUTO` — Trigger A: tutor **approved** the Iris draft unchanged.
- `TUTOR_WRITTEN` — Trigger A: tutor wrote their own answer (no Iris draft used).
- `IRIS_CORRECTED` — Trigger A: tutor **edited** the Iris draft → set `existingAnswer`
  to the edited text and reuse the **same `messageId`** to overwrite a prior entry.

---

## 3. The two ingestion triggers (Artemis logic)

### Trigger A — real-time on tutor verification

When a tutor approves / edits / replaces an Iris draft in the "Messages to Verify"
dashboard, fire the webhook with:

- `source` = `IRIS_AUTO` (approved as-is) | `IRIS_CORRECTED` (edited; set `existingAnswer`) | `TUTOR_WRITTEN` (tutor's own answer),
- `messageId` = the stable id of the posted answer message,
- `verifiedBy` / `verifiedAt` set,
- `thread` = the full thread (mark the Iris draft with `isIrisDraft: true`).

### Trigger B — on thread resolved

When a thread is marked **resolved** via Artemis's existing mechanism **and it did not
already go through the verification dashboard**, fire the webhook with:

- `source` = `THREAD_RESOLVED`,
- `messageId` = the id of the resolving answer message,
- `thread` = the full thread.

Both triggers are event-driven (not scheduled). Trigger B is safely **re-runnable** on
re-resolution (idempotent upsert keyed on `messageId`).

---

## 4. Inbound: status-callback controller (Pyris → Artemis)

Pyris POSTs progress to (mirror the FAQ ingestion status endpoint):

```
POST {artemisBaseUrl}/api/iris/internal/webhooks/ingestion/course-memory/runs/{runId}/status
Authorization: Bearer {runId}          // runId == settings.authenticationToken
Content-Type: application/json
```

Body is a run-state ingestion status update (same shape as FAQ ingestion — the old
stage-based payload has been removed):

```jsonc
{
  "runState": "RUNNING", // RUNNING (in progress) | FINISHED (done) | FAILED
  "error": null, // { "message": "...", "code": "..." } on FAILED, else null
  "tokens": [], // List<TokenUsageDTO>, LLM usage for cost tracking
  "result": null, // ingestion carries no result payload
  "id": null,
}
```

`runState` ∈ `RUNNING | FINISHED | FAILED`. Pyris sends one or more `RUNNING` heartbeats
and exactly one terminal `FINISHED`/`FAILED`. Artemis just needs to accept and
(optionally) surface progress; the entry is stored on Pyris regardless. If Artemis is
unreachable, Pyris logs the failure and **still stores the entry** (callback failures are
non-fatal). Skips (feature disabled, non-public channel) terminate with `FINISHED`.

---

## 5. Retrieval (no new Artemis work)

Retrieval is **not** a separate Artemis call. It runs **inside the autonomous-tutor
pipeline** that Artemis already triggers:

```
POST {pyrisBaseUrl}/api/v1/pipelines/autonomous-tutor/run
```

When a course has stored memory, the agent automatically calls the course-memory tool,
reuses a relevant verified answer, and **cites the source message inline in the generated
text** (the `result` field of the autonomous-tutor status update). The autonomous-tutor
response DTO is unchanged: it still returns `result` (string) + `confidence` (float). No
new fields. So **Artemis needs no changes to consume retrieval** beyond what it already
does for the autonomous tutor.

> If you later want **structured** backlinks (message ids as data rather than inline
> text), that requires adding fields to `AutonomousTutorPipelineStatusUpdateDTO` and the
> callback on the Pyris side — not currently implemented (see Gaps).

---

## 6. Health / feature registration

Pyris now exposes a new feature `COURSE_MEMORY_INGESTION` via its health endpoint
(alongside `FAQ_INGESTION`, `AUTONOMOUS_TUTOR`, …). If Artemis enumerates Pyris features
by name and has a strict enum, **add `COURSE_MEMORY_INGESTION`** (or tolerate unknown
features). Its readiness depends on the `course_memory_ingestion_pipeline` models being
configured in Pyris `llm_config`. The autonomous-tutor feature now also transitively
requires the `course_memory_retrieval_pipeline` models.

---

## 7. Deletion endpoint (Pyris → remove an entry)

When a verified answer is deleted in Artemis or its verification is retracted, POST to:

```
POST {pyrisBaseUrl}/api/v1/webhooks/course-memory/delete
Authorization: <api key>          // same raw-token auth as ingestion
Content-Type: application/json

{
  "settings": { /* same PipelineExecutionSettingsDTO as ingestion */ },
  "courseId": 1,        // int, REQUIRED
  "messageId": "12346"  // string, REQUIRED — the answer message's id (delete key)
}
```

Returns `202 Accepted`; the entry keyed on `(courseId, messageId)` is removed in a
background thread, which reports `FINISHED`/`FAILED` to the §4 status endpoint. Deletion
works even when `course_memory.enabled` is `false` (so operators can purge while the
feature is off), and is coordinated with in-flight ingestion so a delete can't be undone
by an ingestion that started before it.

## 8. Not yet supported on the Pyris side (coordinate if you need these)

- **Structured backlinks in the autonomous-tutor response** (see §5).
- **Correction propagation to near-duplicates** — out of scope by design; only the exact
  `messageId` entry is overwritten.

---

## 9. End-to-end checklist for the Artemis agent

- [ ] New DTOs mirroring §2 (request) and §4 (status body). Stringify `Long` ids.
- [ ] Service method to POST `/api/v1/webhooks/course-memory/ingest` (reuse existing
      Pyris connector auth/base-url/variant handling from FAQ ingestion).
- [ ] **Trigger A** hook in the verification dashboard flow (approve/edit/own-answer →
      correct `source`, set `existingAnswer` on edit, `verifiedBy/At`).
- [ ] **Trigger B** hook on thread-resolved (skip if already verified via dashboard).
- [ ] **Public-channel guard** — only fire for public channels; set `isPublicChannel`.
- [ ] Use a **stable answer-message id** as `messageId` so corrections overwrite.
- [ ] Build the `thread` array (ordered, `authorRole` ∈ student/tutor/iris, mark
      `isIrisDraft`).
- [ ] Controller for the status callback at the §4 path with Bearer-token validation.
- [ ] (Optional) Register/tolerate the `COURSE_MEMORY_INGESTION` health feature.

---

## Appendix: minimal working example (verified against Pyris)

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/course-memory/ingest \
  -H "Authorization: secret" -H "Content-Type: application/json" \
  -d '{
    "settings": {"authenticationToken":"tok","artemisBaseUrl":"http://localhost:9999","selection":"CLOUD_AI","variant":"default"},
    "courseId": 1, "conversationId": "c1", "messageId": "m1",
    "source": "THREAD_RESOLVED", "isPublicChannel": true,
    "thread": [
      {"id":"m0","authorRole":"student","content":"How do I submit the exercise?"},
      {"id":"m1","authorRole":"tutor","content":"Push to your repo before the deadline; the latest push is graded."}
    ]
  }'
```

Correction (overwrites the `m1` entry in place):

```jsonc
{
  "settings": { "...": "..." },
  "courseId": 1,
  "conversationId": "c1",
  "messageId": "m1",
  "source": "IRIS_CORRECTED",
  "existingAnswer": "Corrected: push to your repo; only commits before 23:59 are graded.",
  "verifiedBy": "tutor-42",
  "verifiedAt": "2026-06-21T10:05:00Z",
  "isPublicChannel": true,
  "thread": ["... full thread ..."],
}
```
