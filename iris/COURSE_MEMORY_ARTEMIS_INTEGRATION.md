# Course Memory — Artemis Integration Contract

The contract between Artemis and Iris (Pyris) for Course Memory: stored question/answer pairs mined from
resolved threads of course channels, served to the autonomous tutor.

Guarantees this contract is built around:

1. **Iris only cites from channels every student can read.** Artemis sends the list of such channels with every
   autonomous-tutor run, Iris serves nothing outside it, and Artemis checks the channels again before it publishes a
   reply unreviewed.
2. **Stored content follows Artemis.** Every change that can affect an entry raises the thread's version; the latest
   version wins in Iris, and a nightly sync retracts whatever an immediate update did not reach.
3. **No user identity is stored.** No logins, no ids of people. Messages of authors who opted out of AI, whose account
   is inactive or who no longer exist are redacted.
4. **Tutor-verified means tutor-verified.** Entries labelled as tutor-verified store exactly the text a tutor signed
   off on.
5. **Instances are isolated.** Several Artemis instances may share one Weaviate; every entry is scoped to the
   canonical base URL of its instance.

---

## 1. Authentication and settings

- **Artemis → Iris:** the raw `Authorization` header carries the configured Iris API token, as for FAQ and lecture
  ingestion.
- **Iris → Artemis (status callbacks):** `Authorization: Bearer <runId>`, where `runId` is `settings.authenticationToken`.
- `settings.artemisBaseUrl` is required on every Course Memory request. Iris canonicalises it (lowercase scheme and
  host, no default port, no trailing slash) and uses the result as the instance identity. **It must not change while
  entries exist** (see §8).

## 2. Ingestion — `POST /api/v1/webhooks/course-memory/ingest`

Returns `202 Accepted`; the run reports `RUNNING`/`FINISHED`/`FAILED` to the status endpoint (§6).

```jsonc
{
  "settings": {
    "authenticationToken": "<run id>",
    "artemisBaseUrl": "https://artemis.example",
    "selection": "CLOUD_AI",
    "variant": "default",
  },
  "courseId": 1,
  "conversationId": "12345", // the channel the thread lives in (backlink)
  "postId": "67888", // the thread's root post: one entry per thread
  "messageId": "67890", // the anchor answer (provenance only)
  "version": 12, // >= 1, see §4
  "source": "TUTOR_WRITTEN", // IRIS_AUTO | IRIS_CORRECTED | TUTOR_WRITTEN | THREAD_RESOLVED
  "isPublicChannel": true, // a real boolean; Iris skips anything else
  "verifiedAt": "2026-06-21T10:00:00Z",
  "existingAnswer": "Push to your repo before the deadline.", // required for the three tutor-verified sources
  "thread": [
    // oldest first
    {
      "id": "post-67888",
      "authorRole": "student",
      "content": "How do I submit?",
      "isIrisDraft": false,
      "isVerifiedAnswer": false,
      "resolvesPost": false,
    },
    { "id": "answer-67889", "authorRole": "student", "redacted": true },
    {
      "id": "answer-67890",
      "authorRole": "tutor",
      "content": "Push to your repo before the deadline.",
      "isVerifiedAnswer": true,
      "resolvesPost": true,
    },
  ],
}
```

Rules:

- **Exactly one** message carries `isVerifiedAnswer`: the anchor Artemis selected from persisted state.
- **Tutor-verified sources** (`IRIS_AUTO`, `IRIS_CORRECTED`, `TUTOR_WRITTEN`) must carry `existingAnswer`, the anchor's
  text exactly as the tutor read it. Iris stores it verbatim and only extracts the question. `THREAD_RESOLVED` extracts
  the answer from the messages flagged `resolvesPost`.
- **Redacted messages** carry no content and no flags. A redacted root post is fine; the question is then extracted
  from what the remaining messages make clear.
- **Structured mentions** are sent without their login (`[user]Name(login)[/user]` becomes `Name`).
- The extractor receives the thread as JSON. Flags only come from the fields; text inside `content` cannot set them.

Iris rejects with `422`: missing ids or `source`, a non-boolean `isPublicChannel`, `version` < 1, a thread without
exactly one `isVerifiedAnswer`, a tutor-verified source without `existingAnswer`, a missing or invalid `artemisBaseUrl`.

**Source by sign-off:** a tutor approving an Iris draft in the dashboard → `IRIS_AUTO` (unchanged) or `IRIS_CORRECTED`
(edited); a tutor marking an answer resolving → `TUTOR_WRITTEN`, or `IRIS_AUTO` for an Iris answer that was published on
its own; anyone else marking it resolving → `THREAD_RESOLVED`. A text change by someone below tutor withdraws the
sign-off, so the entry becomes `THREAD_RESOLVED`.

## 3. Retraction — `POST /api/v1/webhooks/course-memory/delete`

Always one thread:

```jsonc
{ "settings": { ... }, "courseId": 1, "postId": "67888", "version": 13 }
```

Iris writes a **tombstone** carrying `version` instead of removing the object, so an older ingestion that finishes
later finds a newer version and gives up. A retraction older than the stored state is ignored; an equal version still
applies. For a deleted thread Artemis sends `9223372036854775807` (`Long.MAX_VALUE`). Deletion needs no model and works
while `course_memory.enabled` is `false`. There are no channel- or course-wide deletions: readable channels are enforced
at read time (§5) and the nightly sync (§7) removes what deleted channels and courses left behind.

## 4. Ordering: the version

Every operation on a thread carries a monotonic per-thread version (`post.course_memory_version` in Artemis, minted
atomically before the thread is read). Iris keeps the highest version per thread and drops anything not newer.

Artemis also bumps the version **in the same transaction as** every change that can make a stored entry outdated:
editing or deleting a message of the thread, an opt-out from AI, a deactivation, the deletion of an account's
messages. If the follow-up refresh never reaches Iris, the stored entry has an older version than Artemis, and the
nightly sync retracts it.

## 5. Retrieval inside the autonomous tutor

Artemis sends `courseMemoryConversationIds` with every run of `/api/v1/pipelines/autonomous-tutor/run`: the channels of
the course that every student can read **at dispatch time** (public or course-wide, not an exam channel, exercise
released). Iris filters every Course Memory query by this list, by the instance and by the course, and checks each hit
again. A missing or empty list means no Course Memory for the run.

The final status update reports `usedCourseMemoryConversationIds`: the channels of every entry the run retrieved.
Before Artemis publishes a reply without review it checks them against a fresh list, before and after saving; a reply
whose sources are no longer readable, or that reports none, goes to tutor review.

Organizational facts (dates, rooms, deadlines, grading, exam scope, …) in a reply that would be published unreviewed
are checked by an LLM against the answers of tutor-verified entries; anything not explicitly backed sends the reply to
review. FAQs do not count as evidence until FAQ entries are scoped to their instance.

## 6. Status callback (Iris → Artemis)

`POST {artemisBaseUrl}/api/iris/internal/webhooks/ingestion/course-memory/runs/{runId}/status`, body
`{ "runState": "RUNNING" | "FINISHED" | "FAILED", "error": {...} | null, "tokens": [...] }`. One or more `RUNNING`,
exactly one terminal state. Skips (feature disabled, non-public channel) finish with `FINISHED`.

## 7. Nightly sync

Two endpoints, both `202 Accepted`, processed in the background; no status callback.

- `POST /api/v1/webhooks/course-memory/sync/instance` — `{ settings, snapshotAt, courseIds }`: every course that
  exists. Iris retracts the live entries of every other course of this instance.
- `POST /api/v1/webhooks/course-memory/sync/course` — `{ settings, snapshotAt, courseId, threads: [{ postId, version,
eligible }] }`: the **complete** list of the course's threads that have a version. Iris, per object of the course:
  listed and eligible with stored version ≥ listed → keep; listed and eligible with an older stored version → retract
  at the listed version; listed but not eligible → retract at the listed version; not listed (thread deleted) →
  retract at the stored version, unless the object was written after `snapshotAt` minus a 5-minute margin.

Artemis runs the sync on its scheduling node (`artemis.iris.course-memory.sync-cron`, default 03:00; `-` disables it).

## 8. Operations

- **Exactly one Iris process writes the CourseMemory collection.** Ordering is enforced by a compare-and-write under
  an in-process lock. Run one container without `--workers`, never two installations on the same collection, and no
  overlapping replacement during a deploy. Iris logs an error when it detects `WEB_CONCURRENCY` > 1.
- **Changing Artemis's `server.url`:** stop Artemis, wait until Iris runs no Course Memory work (or restart Iris),
  delete every object whose `base_url` is the old canonical URL, check that none remains, then change the URL and start
  Artemis. Entries of the old URL can otherwise never be served or retracted.
- On first start after this version Iris deletes Course Memory objects without `base_url` (pre-isolation data).
