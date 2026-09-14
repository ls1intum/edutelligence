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
   Artemis already invokes. See [Retrieval](#5-retrieval-no-new-artemis-work).

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
  "conversationId": "12345", // string, REQUIRED — the CHANNEL id (backlink only)
  "postId": "67888", // string, REQUIRED — thread root post id; UPSERT KEY
  "messageId": "67890", // string, REQUIRED — answer that triggered this event (provenance)
  "version": 12, // int >= 1, REQUIRED — monotonic per-thread operation version, see §2b
  "source": "THREAD_RESOLVED", // enum, REQUIRED — see below
  "isPublicChannel": true, // bool — MUST be a real JSON boolean and true

  "thread": [
    // ordered oldest→newest; full thread. At least one message MUST carry
    // isVerifiedAnswer or resolvesPost, otherwise Pyris rejects the payload.
    {
      "id": "67888",
      "authorRole": "student",
      "content": "How do I submit?",
      "createdAt": "2026-06-21T09:58:00Z",
      "isIrisDraft": false,
      "isVerifiedAnswer": false,
      "resolvesPost": false,
    },
    {
      "id": "67889",
      "authorRole": "student",
      // Author opted out of AI: no content, and the flags below MUST be false.
      // "content" may be omitted entirely (Artemis drops empty strings on the wire).
      "redacted": true,
      "createdAt": "2026-06-21T09:59:00Z",
      "isIrisDraft": false,
      "isVerifiedAnswer": false,
      "resolvesPost": false,
    },
    {
      "id": "67890",
      "authorRole": "tutor",
      "content": "Push to your repo before the deadline.",
      "createdAt": "2026-06-21T10:00:00Z",
      "isIrisDraft": false,
      "isVerifiedAnswer": false, // at most ONE message in the thread may set this
      "resolvesPost": true, // several resolving answers are allowed and get merged
    },
  ],

  "verifiedBy": "tutor-42", // optional string — who verified (Trigger A)
  "verifiedAt": "2026-06-21T10:00:00Z", // optional ISO-8601 string
  "existingAnswer": null, // optional string — see IRIS_CORRECTED below
}
```

### Field semantics / invariants

| Field                       | Type       | Notes                                                                                                                                                                                                                                                                                                                                                                                               |
| --------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `courseId`                  | int        | Required. Scopes every search; entries are never returned cross-course.                                                                                                                                                                                                                                                                                                                             |
| `conversationId`            | **string** | Artemis ids are `Long` — **stringify them**. The **channel** the thread lives in, not the thread itself. Backlinking only.                                                                                                                                                                                                                                                                          |
| `postId`                    | **string** | **Stringify. This is the dedup/upsert key**: Pyris maps `(courseId, postId)` to a deterministic UUID. Use the **thread root post's** id. One resolved thread yields exactly one entry, so a later correction or an additional resolving answer **overwrites** it.                                                                                                                                   |
| `messageId`                 | **string** | **Stringify.** The answer message whose event triggered this ingestion. Stored as **provenance only** — it is deliberately _not_ the key and is never matched against `thread[].id`.                                                                                                                                                                                                                |
| `version`                   | int        | **Required, ≥ 1.** Monotonic per-thread operation version (see §2b). Pyris stores it with the entry and ignores any later-arriving ingestion or retraction whose version is not newer than the stored one, so the latest state Artemis dispatched always wins.                                                                                                                                      |
| `source`                    | enum       | One of `IRIS_AUTO`, `TUTOR_WRITTEN`, `IRIS_CORRECTED`, `THREAD_RESOLVED`.                                                                                                                                                                                                                                                                                                                           |
| `isPublicChannel`           | bool       | Must be a **real JSON boolean** — `"true"`/`1` are rejected, not coerced. Send `true` only for public channels; Pyris skips ingestion if `false` (defense in depth — **Artemis must only fire for public channels**, req. 5).                                                                                                                                                                       |
| `thread`                    | array      | Full thread, **ordered oldest→newest**. Pyris truncates to `context_message_limit` (default 20) messages — always keeping the root post and every flagged message — but send the whole thread.                                                                                                                                                                                                      |
| `thread[].id`               | **string** | Backlink only. Post and answer ids come from **separate Artemis tables with independent sequences**, so a root post and one of its answers routinely share a number — namespace-qualify them (`post-7` / `answer-7`) to keep the thread's ids distinct.                                                                                                                                             |
| `thread[].authorRole`       | string     | Use `"student"`, `"tutor"`, or `"iris"`. Weights the extraction.                                                                                                                                                                                                                                                                                                                                    |
| `thread[].isIrisDraft`      | bool       | Mark the Iris-generated draft message `true` so the extractor knows it was AI-authored.                                                                                                                                                                                                                                                                                                             |
| `thread[].isVerifiedAnswer` | bool       | **The answer anchor.** Set on the single answer whose verification/resolution triggered _this_ event (the message `messageId` refers to). **At most one per thread** — Artemis derives it from one triggering answer, so duplicates are rejected as an upstream bug.                                                                                                                                |
| `thread[].resolvesPost`     | bool       | The durable Artemis `resolvesPost` flag. **Several are legitimate** (a post is resolved if _any_ answer resolves it); Pyris merges them into one answer.                                                                                                                                                                                                                                            |
| `thread[].redacted`         | bool       | The author opted out of AI. Send an empty/absent `content` and **clear `isVerifiedAnswer` / `resolvesPost`** — Pyris renders the message as a placeholder so the thread still reads in order, and a placeholder must never be merged into the stored answer.                                                                                                                                        |
| `existingAnswer`            | string     | **Required and non-blank when `source` is `IRIS_AUTO` or `IRIS_CORRECTED`.** Pyris stores this text as the answer **verbatim** (still derives the canonical question from the thread). Both sources mean a tutor signed off on one specific wording in the dashboard — unchanged or edited — and storing the extractor's paraphrase instead would serve, as tutor-approved, text no tutor ever saw. |

The extractor synthesizes the stored answer **only** from messages flagged
`isVerifiedAnswer` / `resolvesPost` — it never guesses which message is the answer, and
never infers it from `messageId`. That is why an unflagged thread is rejected instead of
silently stored under a tutor-verified label it did not earn.

### Payloads Pyris rejects (`422`, before anything is stored)

- `courseId`, `conversationId`, `postId`, `messageId` or `source` missing.
- `isPublicChannel` sent as a string or number instead of a boolean.
- `version` missing, or below 1.
- **No** thread message flagged `isVerifiedAnswer` or `resolvesPost`.
- **More than one** message flagged `isVerifiedAnswer`.
- `source = IRIS_AUTO` or `source = IRIS_CORRECTED` with a missing or blank `existingAnswer`.

### `source` value → which trigger

- `THREAD_RESOLVED` — Trigger B: the thread was marked resolved by someone who is not a
  tutor, so nobody with authority signed off on the answer.
- `IRIS_AUTO` — a tutor **approved** the Iris draft unchanged (Trigger A), or marked an
  auto-published Iris answer as resolving (Trigger B) → set `existingAnswer` to the
  answer's text verbatim.
- `TUTOR_WRITTEN` — a tutor endorsed a human-written answer: wrote it in the dashboard
  (Trigger A) or marked it resolving (Trigger B).
- `IRIS_CORRECTED` — Trigger A: tutor **edited** the Iris draft → set `existingAnswer`
  to the edited text. The **same `postId`** overwrites the thread's prior entry.

The trust tier follows the **endorsement**, not the authorship: a student's answer a tutor
marks resolving is `TUTOR_WRITTEN`; a tutor's answer a student marks resolving is
`THREAD_RESOLVED`. Artemis derives it from the endorser recorded on the resolving answer
itself (`AnswerPost.resolvedBy`), never from whoever happened to trigger the refresh.

### 2b. Ordering: the operation version

Ingestions and retractions run asynchronously on Pyris and can be accepted or finish in
any order. Artemis therefore stamps every thread-scoped operation with a **monotonic
per-thread version**, and Pyris applies a simple rule: **the stored object keeps the
highest version it has seen, and any operation carrying a version that is not newer is
dropped.** A retraction does not delete the object but turns it into a **tombstone**
(`deleted = true`) that keeps its version, so an ingestion accepted before the retraction
finds a newer version when it finally writes and gives up, instead of re-inserting the
retracted answer into an empty slot. Equally, an older extraction can no longer overwrite
the entry a newer edit produced. Tombstones are invisible to retrieval and are overwritten
in place by a later ingestion with a higher version (the thread was re-resolved).

What Artemis has to do:

- Keep one counter per thread (`post.course_memory_version`) and **increment it atomically
  in the database** once per ingestion or thread retraction it dispatches. Mint the version
  **before** reading the thread you serialize, so the operation with the highest version
  always describes at least everything committed before it was minted.
- Send that value as `version` on the ingestion payload and on the `postId`-scoped
  deletion payload.
- When the **thread itself is deleted**, its row is gone and nothing can be minted: send
  `9223372036854775807` (`Long.MAX_VALUE`). Post ids are never reused, so nothing
  legitimate can follow.
- Channel- and course-scoped deletions carry **no** version; see §7.

Because the version decides, provenance no longer does: a newer `THREAD_RESOLVED` write
**does** replace an older tutor-verified entry. That is deliberate — Artemis only sends it
when the tutor-verified answer is gone (deleted or un-marked) and a community-resolved one
is all that remains, and refusing the write would keep serving the retracted text as
tutor-verified. Artemis ranks tutor-endorsed anchors above community-resolved ones when
choosing what to send, so a student marking a second answer never demotes a standing
tutor-verified entry.

---

## 3. The two ingestion triggers (Artemis logic)

### Trigger A — real-time on tutor verification

When a tutor approves / edits / replaces an Iris draft in the "Messages to Verify"
dashboard, fire the webhook with:

- `source` = `IRIS_AUTO` (approved as-is; set `existingAnswer` to the approved text) |
  `IRIS_CORRECTED` (edited; set `existingAnswer` to the edit) | `TUTOR_WRITTEN` (tutor's own answer),
- `postId` = the **thread root post's** id (the upsert key),
- `messageId` = the id of the just-verified answer message (provenance),
- `version` = the thread's next operation version (§2b),
- `thread` = the full thread with that same answer flagged `isVerifiedAnswer: true`
  (mark the Iris draft with `isIrisDraft: true`),
- `verifiedBy` / `verifiedAt` set.

### Trigger B — on thread resolved

When a thread is marked **resolved** via Artemis's existing mechanism **and it did not
already go through the verification dashboard**, fire the webhook with:

- `source` = `THREAD_RESOLVED` when the endorser of the anchoring answer is not a tutor,
  otherwise `TUTOR_WRITTEN` (human answer) or `IRIS_AUTO` (auto-published Iris answer;
  send its text as `existingAnswer`),
- `postId` = the **thread root post's** id (the upsert key),
- `messageId` = the id of the resolving answer message (provenance),
- `version` = the thread's next operation version (§2b),
- `thread` = the full thread with **every** answer carrying Artemis's `resolvesPost`
  flag marked `resolvesPost: true`, and the answer that just triggered the event also
  marked `isVerifiedAnswer: true`.

Both triggers are event-driven (not scheduled). Trigger B is safely **re-runnable** on
re-resolution (idempotent upsert keyed on `postId`, ordered by `version`).

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

Each retrieved entry carries a ready-made Artemis deep link
(`{artemisBaseUrl}/courses/{courseId}/communication?conversationId=…&focusPostId=…&openThreadOnFocus=1`),
built by Pyris from the stored `courseId` / `conversationId` / `postId`, and the agent is
instructed to cite it as a markdown link. Raw message ids are deliberately not offered as
a citation target: they are ambiguous (posts and answer posts have independent id
sequences) and mean nothing to a student.

> If you later want **structured** backlinks (link/ids as response _data_ rather than
> inline text), that requires adding fields to `AutonomousTutorPipelineStatusUpdateDTO`
> and the callback on the Pyris side — not currently implemented (see Gaps).

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
  "settings": { /* same PipelineExecutionSettingsDTO as ingestion; REQUIRED, non-null */ },
  "courseId": 1,      // int, REQUIRED
  "postId": "67888",  // string — the thread ROOT POST id (delete key)
  "version": 13       // int >= 1, REQUIRED with postId — see §2b; Long.MAX_VALUE for a deleted thread
  // OR, instead of postId + version:
  // "conversationId": "12345"  // string — delete EVERY entry mined from this channel
  // OR:
  // "wholeCourse": true        // the course itself was deleted
}
```

**Exactly one** of `postId` / `conversationId` / `wholeCourse` must be present; neither or
several is rejected as a bad request, because a deletion that quietly does the wrong amount
is worse than one that fails loudly. `version` is **required with `postId`** and rejected
as missing otherwise.

- **`postId`** — a single thread stopped being memory-worthy. Send the **same `postId`
  used at ingestion**: the entry is keyed on the thread, not on the answer message, so
  deleting by an answer id removes nothing. Pyris does not remove the object but writes a
  **tombstone** carrying `version`; a retraction whose version is older than the stored
  state is ignored (the thread was re-resolved since), an equal version still applies.
- **`conversationId`** — a whole channel was deleted or stopped being public. Channel
  eligibility is only evaluated when an entry is _written_, so without this an answer
  ingested while the channel was public keeps being served after it is restricted.
  Artemis fires this from channel deletion and from the channel privacy toggle.

Returns `202 Accepted`; the entry keyed on `(courseId, postId)` is retracted in a
background thread, which reports `FINISHED`/`FAILED` to the §4 status endpoint (a
retraction dropped as stale still reports `FINISHED` — it was superseded, not failed).
Deletion works even when `course_memory.enabled` is `false` (so operators can purge while
the feature is off). Thread retractions are ordered against in-flight ingestions by
`version` (§2b); channel and course purges are ordered in-process, see §8.

## 8. Not yet supported on the Pyris side (coordinate if you need these)

- **Structured backlinks in the autonomous-tutor response** (see §5).
- **Correction propagation to near-duplicates** — out of scope by design; only the
  thread's own `postId` entry is overwritten.
- **Multi-replica Pyris deployments** — per-thread ordering is durable (the version is
  stored on the object), but the compare-and-write is only atomic within one process.
  Two replicas racing on the same thread can still misorder within the read–compare–write
  of a single object; the window used to be the whole extraction.
- **Channel- and course-wide deletion are ordered against in-flight ingestion in-process
  only.** They delete by filter across threads whose keys are not known up front, so they
  cannot leave a versioned tombstone per thread; an ingestion accepted before the purge
  is refused at write time by an in-process counter instead. On a single replica this
  is exact; across replicas an ingestion running elsewhere may still land after the
  purge. Artemis stops emitting ingestions for the channel at the same moment, so the
  window is small; re-running the deletion clears any straggler.

---

## 9. End-to-end checklist for the Artemis agent

- [ ] New DTOs mirroring §2 (request) and §4 (status body). Stringify `Long` ids.
- [ ] Service method to POST `/api/v1/webhooks/course-memory/ingest` (reuse existing
      Pyris connector auth/base-url/variant handling from FAQ ingestion).
- [ ] **Trigger A** hook in the verification dashboard flow (approve/edit/own-answer →
      correct `source`, set `existingAnswer` verbatim for `IRIS_AUTO` and `IRIS_CORRECTED`,
      `verifiedBy/At`).
- [ ] **Trigger B** hook on thread-resolved, deriving `source` / `verifiedBy` / `verifiedAt`
      from the endorser recorded on the resolving answer (not from the acting user), and
      preferring a tutor-endorsed or dashboard-verified anchor over a community-resolved one.
- [ ] **Version** — a per-thread counter incremented atomically per dispatched ingestion
      or thread retraction, minted before the thread is serialized, sent as `version`;
      `Long.MAX_VALUE` when the thread itself was deleted (§2b).
- [ ] **Public-channel guard** — only fire for public channels; set `isPublicChannel` as
      a real boolean.
- [ ] Send the **thread root post's id** as `postId` so corrections and further resolving
      answers overwrite the thread's single entry; send the triggering answer's id as
      `messageId`.
- [ ] Build the `thread` array (ordered, `authorRole` ∈ student/tutor/iris, mark
      `isIrisDraft`) and **flag the answer anchor** — exactly one `isVerifiedAnswer`,
      plus `resolvesPost` on every answer Artemis marks as resolving.
- [ ] Delete by **`postId`** (with `version`), matching the id used at ingestion.
- [ ] Controller for the status callback at the §4 path with Bearer-token validation.
- [ ] (Optional) Register/tolerate the `COURSE_MEMORY_INGESTION` health feature.

---

## Appendix: minimal working example (verified against Pyris)

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/course-memory/ingest \
  -H "Authorization: secret" -H "Content-Type: application/json" \
  -d '{
    "settings": {"authenticationToken":"tok","artemisBaseUrl":"http://localhost:9999","selection":"CLOUD_AI","variant":"default"},
    "courseId": 1, "conversationId": "c1", "postId": "post-1", "messageId": "answer-1",
    "version": 1, "source": "THREAD_RESOLVED", "isPublicChannel": true,
    "thread": [
      {"id":"post-1","authorRole":"student","content":"How do I submit the exercise?"},
      {"id":"answer-1","authorRole":"tutor","content":"Push to your repo before the deadline; the latest push is graded.","isVerifiedAnswer":true,"resolvesPost":true}
    ]
  }'
```

Correction (overwrites the `post-1` thread entry in place; note the higher `version`):

```jsonc
{
  "settings": { "...": "..." },
  "courseId": 1,
  "conversationId": "c1",
  "postId": "post-1", // same thread → overwrites the entry above
  "messageId": "answer-2", // the corrected answer message
  "version": 2, // newer than the entry above, so it is applied
  "source": "IRIS_CORRECTED",
  "existingAnswer": "Corrected: push to your repo; only commits before 23:59 are graded.",
  "verifiedBy": "tutor-42",
  "verifiedAt": "2026-06-21T10:05:00Z",
  "isPublicChannel": true,
  "thread": [
    {
      "id": "post-1",
      "authorRole": "student",
      "content": "How do I submit the exercise?",
    },
    {
      "id": "answer-2",
      "authorRole": "tutor",
      "content": "Corrected: push to your repo; only commits before 23:59 are graded.",
      "isVerifiedAnswer": true,
    },
  ],
}
```

Deletion of that same entry:

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/course-memory/delete \
  -H "Authorization: secret" -H "Content-Type: application/json" \
  -d '{
    "settings": {"authenticationToken":"tok","artemisBaseUrl":"http://localhost:9999","selection":"CLOUD_AI","variant":"default"},
    "courseId": 1, "postId": "post-1", "version": 3
  }'
```
