# Course Memory — Testing Guide

How to test the Course Memory feature (Pyris side): a standalone Weaviate-backed
store of tutor-verified Q/A pairs that the autonomous tutor retrieves (course-scoped,
hybrid search) to give consistent answers to recurring questions.

Three levels, easiest first:

1. **Unit tests** — no setup.
2. **Live Weaviate round-trip** — real Weaviate, stubbed embedding (no LLM credentials).
3. **Full end-to-end over HTTP** — real LLM extraction + agent tool.

All commands assume you are in `edutelligence/iris`.

---

## 1. Unit tests (fastest, no setup)

```bash
poetry run pytest tests/test_course_memory_*.py -q
```

The tests cover:

- schema index flags, the `base_url` instance property (exact matching) and `written_at`,
  the migration that removes objects without an instance, and the retry of a failed
  initialisation through `VectorDatabase()`,
- retrieval: threshold, course and instance scoping, the required channel allowlist (with
  an exact post-filter), tombstone filtering, graceful degradation, backlinks,
- extraction: JSON parsing, the JSON thread (messages cannot forge flags), verbatim
  answers for every tutor-verified source, only the anchor for tutor-verified entries,
  redacted messages and a redacted root,
- upsert keyed on the instance and the thread, **version ordering** (a stale ingestion or
  retraction is dropped, a retraction leaves a versioned tombstone, a newer write
  replaces a tombstone),
- the nightly sync (outdated, ineligible and deleted threads, deleted courses, the
  snapshot margin, other instances untouched),
- the organizational evidence check (strict verdicts, fail-closed cases, review-everything
  mode),
- wire-contract validation and the non‑public‑channel and feature‑disabled skips.

Run the full suite to confirm no regressions:

```bash
poetry run pytest -q
```

---

## 2. Live Weaviate round-trip (no LLM credentials)

This proves the real storage/retrieval path against a running Weaviate using a
**stubbed embedding** (so no LLM keys are needed), then deletes the `CourseMemory`
collection so your Weaviate is left clean.

It verifies: ingest + retrieve with backlink ids, **course and instance scoping** (one
course's or one Artemis instance's entries never leak into another), the **channel
allowlist** (an entry outside the listed channels is never returned), **correction
overwrite** (re‑ingesting the same `postId` updates the answer in place), and **graceful
degradation** (embedding error → empty result, no crash).

### Prerequisites

- Weaviate running and reachable at the host/port in `application.local.yml`
  (default `localhost:8001`, gRPC `50051`). Quick check:
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/v1/.well-known/ready
  # expect: 200
  ```

### Save the script as `cm_verify.py` (e.g. in `/tmp`)

```python
"""Manual verification of Course Memory against the live local Weaviate.

Uses a stubbed embedding (no LLM credentials needed) and deletes the
CourseMemory collection at the end so your Weaviate is left clean.
"""
import os

os.environ.setdefault("APPLICATION_YML_PATH", "./application.local.yml")
os.environ.setdefault("LLM_CONFIG_PATH", "./llm_config.local.yml")

import iris.domain  # noqa: F401  (resolve import cycle)
from iris.config import settings
from iris.domain.data.course_memory_dto import CourseMemorySource
from iris.pipeline.course_memory_ingestion_pipeline import CourseMemoryIngestionPipeline
from iris.retrieval.course_memory_retrieval import CourseMemoryRetrieval
from iris.vector_database.database import VectorDatabase

COURSE = 90001
OTHER_COURSE = 90002
BASE = "https://artemis.example"
OTHER_BASE = "https://other-artemis.example"


def fake_vec(text: str):
    """Deterministic 8-dim pseudo-embedding (consistent across calls)."""
    h = abs(hash(text))
    return [((h >> (i * 4)) & 0xF) / 15.0 for i in range(8)]


class FakeEmbed:
    def embed(self, text):
        return fake_vec(text)


def make_ingestion(dto):
    p = object.__new__(CourseMemoryIngestionPipeline)
    p.collection = db.course_memory
    p.llm_embedding = FakeEmbed()
    p.dto = dto
    return p


class DTO:
    def __init__(self, post_id, message_id, course_id, source, version=1, base_url=BASE):
        # post_id is the upsert key (the thread root); message_id is provenance;
        # version orders the write against the thread's other operations.
        self.post_id = post_id
        self.message_id = message_id
        self.course_id = course_id
        self.conversation_id = "11"
        self.source = source
        self.version = version
        self.verified_at = "2026-06-21T10:00:00Z"
        self.base_url = base_url


def ask(retr, query, course_id=COURSE, base_url=BASE, channels=(11,)):
    return retr(chat_history=[], student_query=query, course_id=course_id,
                base_url=base_url, allowed_conversation_ids=list(channels), rewrite=False)


db = VectorDatabase()
# Make the demo deterministic: don't gate on the hybrid score here (threshold
# behaviour is covered by the unit tests).
settings.course_memory.similarity_threshold = 0.0

try:
    print("1) Ingest two verified Q/A pairs for course", COURSE)
    make_ingestion(DTO("post-1", "answer-1", COURSE, CourseMemorySource.THREAD_RESOLVED)).upsert(
        "How do I submit the programming exercise?",
        "Push to your personal repository before the deadline; the latest push is graded.",
    )
    make_ingestion(DTO("post-2", "answer-2", COURSE, CourseMemorySource.TUTOR_WRITTEN)).upsert(
        "When is the exam?",
        "The exam is on July 30th, 14:00, in lecture hall MI HS1.",
    )

    print("2) Ingest one entry for a DIFFERENT course (scoping check)")
    make_ingestion(DTO("post-9", "answer-9", OTHER_COURSE, CourseMemorySource.THREAD_RESOLVED)).upsert(
        "How do I submit?", "Other course answer — must NOT appear for course 90001."
    )

    retr = object.__new__(CourseMemoryRetrieval)
    retr.llm_embedding = FakeEmbed()
    retr.collection = db.course_memory

    print("\n3) Retrieve for course", COURSE, "(rewrite off, no LLM):")
    results = ask(retr, "how to submit exercise")
    for r in results:
        print(f"   - [thread={r['post_id']} src msg={r['message_id']}] "
              f"Q={r['question']!r} A={r['answer'][:40]!r}...")

    print("\n4) Course scoping: querying OTHER_COURSE returns only its own entry:")
    other = ask(retr, "how to submit", course_id=OTHER_COURSE)
    print("   post_ids:", [r["post_id"] for r in other],
          "->", "OK" if all(r["post_id"] == "post-9" for r in other) else "LEAK!")

    print("\n4b) Instance and channel scoping")
    make_ingestion(DTO("post-1", "answer-x", COURSE, CourseMemorySource.THREAD_RESOLVED, base_url=OTHER_BASE)).upsert(
        "How do I submit the programming exercise?", "Other instance answer - must NOT appear."
    )
    mine = ask(retr, "how to submit exercise")
    print("   other instance hidden:", all("Other instance" not in r["answer"] for r in mine))
    print("   channel not listed -> nothing:", ask(retr, "how to submit exercise", channels=(99,)) == [])

    print("\n5) Correction overwrite: re-ingest thread post-2 with a corrected answer + source IRIS_CORRECTED")
    # New answer message on the SAME thread: keyed on post_id, so it replaces
    # the entry rather than adding a near-duplicate. version=2 is newer than the
    # entry's version=1, so the write is applied.
    make_ingestion(DTO("post-2", "answer-2b", COURSE, CourseMemorySource.IRIS_CORRECTED, version=2)).upsert(
        "When is the exam?", "CORRECTED: the exam moved to August 5th, 09:00, MI HS2.",
    )
    count = db.course_memory.aggregate.over_all(total_count=True).total_count
    after = ask(retr, "when is the exam")
    exam = [r for r in after if r["post_id"] == "post-2"]
    print(f"   total objects in collection = {count} (no duplicate for post-2)")
    print(f"   post-2 answer now = {exam[0]['answer']!r}")

    print("\n6) Ordering: a stale ingestion (version=1) must not overwrite the correction")
    make_ingestion(DTO("post-2", "answer-2", COURSE, CourseMemorySource.THREAD_RESOLVED, version=1)).upsert(
        "When is the exam?", "STALE: the exam is on July 30th.",
    )
    stale = [r for r in ask(retr, "when is the exam") if r["post_id"] == "post-2"]
    print("   post-2 answer still =", repr(stale[0]["answer"][:9]), "->", "OK" if stale[0]["answer"].startswith("CORRECTED") else "STALE WRITE LANDED!")

    print("\n7) Retraction: a versioned tombstone hides the entry and blocks a late ingestion")
    from iris.pipeline.course_memory_ingestion_pipeline import CourseMemoryDeleter
    CourseMemoryDeleter.for_collection(db.course_memory).delete_for_thread(BASE, "post-2", COURSE, version=3)
    make_ingestion(DTO("post-2", "answer-2c", COURSE, CourseMemorySource.TUTOR_WRITTEN, version=2)).upsert(
        "When is the exam?", "LATE: this ingestion was accepted before the retraction.",
    )
    gone = [r for r in ask(retr, "when is the exam") if r["post_id"] == "post-2"]
    count = db.course_memory.aggregate.over_all(total_count=True).total_count
    print(f"   post-2 retrievable = {bool(gone)} (expect False); objects in collection = {count} (tombstone kept)")

    print("\n8) Graceful degradation: embedding service raises -> retrieval returns []")
    class Boom:
        def embed(self, t):
            raise RuntimeError("Logos unavailable")
    retr.llm_embedding = Boom()
    print("   result:", ask(retr, "x"))

    print("\nALL CHECKS DONE ✅")
finally:
    print("\nCleaning up: deleting CourseMemory collection so Weaviate is left clean.")
    db.delete_collection("CourseMemory")
```

### Run it

```bash
APPLICATION_YML_PATH=./application.local.yml LLM_CONFIG_PATH=./llm_config.local.yml \
poetry run python /tmp/cm_verify.py
```

### Expected output (abridged)

```
3) Retrieve for course 90001 (rewrite off, no LLM):
   - [thread=post-1 src msg=answer-1] Q='How do I submit the programming exercise?' A='Push to your personal repository before '...
   - [thread=post-2 src msg=answer-2] Q='When is the exam?' A='The exam is on July 30th, 14:00, in lect'...

4) Course scoping: ... post_ids: ['post-9'] -> OK
4b) Instance and channel scoping: other instance hidden: True, channel not listed -> nothing: True
5) Correction overwrite: total objects in collection = 4 (no duplicate for post-2)
   post-2 answer now = 'CORRECTED: the exam moved to August 5th, 09:00, MI HS2.'
6) Ordering: ... post-2 answer still = 'CORRECTED' -> OK
7) Retraction: post-2 retrievable = False (expect False); objects in collection = 4 (tombstone kept)
8) Graceful degradation: ... result: []
ALL CHECKS DONE ✅
```

> Note: you may see a log line `Collection CourseMemory failed to delete` during
> cleanup. It's a **false alarm** — Weaviate v4's `collections.delete()` returns
> `None`, which the existing `VectorDatabase.delete_collection` helper misreports.
> The collection is actually deleted; confirm with:
>
> ```bash
> poetry run python -c "import weaviate; c=weaviate.connect_to_custom(http_host='localhost',http_port=8001,http_secure=False,grpc_host='localhost',grpc_port=50051,grpc_secure=False); print('exists:', c.collections.exists('CourseMemory')); c.close()"
> ```

---

## 3. Full end-to-end over HTTP (needs working LLM + embedding credentials)

This exercises the real LLM Q/A extraction (ingestion) and the agent tool (retrieval).

### Start the server

```bash
APPLICATION_YML_PATH=./application.local.yml LLM_CONFIG_PATH=./llm_config.local.yml \
poetry run uvicorn iris.main:app --reload
```

### Trigger ingestion (Trigger A / Trigger B)

The auth header is the **raw token** from `application.local.yml` `api_keys`
(default `secret`) — **not** a `Bearer` prefix. `source` distinguishes the trigger:
`THREAD_RESOLVED` (Trigger B), or `IRIS_AUTO` / `TUTOR_WRITTEN` / `IRIS_CORRECTED`
(Trigger A, tutor verification).

```bash
curl -X POST http://localhost:8000/api/v1/webhooks/course-memory/ingest \
  -H "Authorization: secret" -H "Content-Type: application/json" \
  -d '{
    "settings": {"authenticationToken":"tok","artemisBaseUrl":"http://localhost:9999","selection":"CLOUD_AI","variant":"default"},
    "courseId": 1, "conversationId": "11", "postId": "post-1", "messageId": "answer-1",
    "version": 1, "source": "THREAD_RESOLVED", "isPublicChannel": true,
    "thread": [
      {"id":"post-1","authorRole":"student","content":"How do I submit the exercise?"},
      {"id":"answer-1","authorRole":"tutor","content":"Push to your repo before the deadline; the latest push is graded.","isVerifiedAnswer":true,"resolvesPost":true}
    ]
  }'
```

- Returns `202 Accepted` immediately; the pipeline runs in a background thread.
- The status callback POSTs to `artemisBaseUrl/.../status`. If no Artemis is
  listening, that failure is **logged and non-fatal** — the entry still stores.
- **Correction test:** re-send the same `postId` with a higher `"version"`,
  `"source": "IRIS_CORRECTED"` and a non-blank `"existingAnswer": "..."` to confirm the
  entry is overwritten in place (no duplicate), even with a different `messageId`.
- **Ordering test:** re-send the original payload (`"version": 1`) after the correction —
  it returns `202` but the log says `Ignoring stale course memory ingestion`, and the
  corrected answer stays.
- **Validation tests (expect `422`, nothing stored):** drop `postId`; drop `version` or
  send `0`; send `"isPublicChannel": "true"` as a string; send a thread without exactly one
  `isVerifiedAnswer`; send `IRIS_AUTO`, `IRIS_CORRECTED` or `TUTOR_WRITTEN` with a blank
  `existingAnswer`; leave out `settings.artemisBaseUrl`.
- **Deletion test:** `POST /api/v1/webhooks/course-memory/delete` with
  `{"settings": {...}, "courseId": 1, "postId": "post-1", "version": 3}` — the delete key
  is the thread root, not the answer message, and `version` is required with it. The
  entry is not removed but tombstoned: it disappears from retrieval, and re-sending the
  `"version": 1` ingestion afterwards is dropped as stale.

### Confirm retrieval via the autonomous tutor

Send a related question to the autonomous tutor for the same course and watch the
agent call the course-memory tool and cite the source message:

```
POST /api/v1/pipelines/autonomous-tutor/run
```

(Use an `AutonomousTutorPipelineExecutionDTO` with `course.id = 1`, a `post` asking a
question similar to a stored one, and `"courseMemoryConversationIds": [11]` — without the
channel of the stored entry in that list the tool is not even offered.) The final status
update reports `usedCourseMemoryConversationIds`. With LangFuse enabled you can trace the
tool calls.

---

## Gotchas

- **Embedding model must match** between ingestion and retrieval. In
  `application.local.yml` both `course_memory_ingestion_pipeline` and
  `course_memory_retrieval_pipeline` use `Qwen/Qwen3-Embedding-8B`. Mixing models
  corrupts the vector space.
- **Vector dimension is locked on first write.** If you seed with one embedding
  model and later switch, delete the `CourseMemory` collection first (see the
  cleanup snippet above).
- **Threshold is an absolute cosine-certainty floor.** Retrieval ranks candidates with
  a hybrid query, then gates them with a `near_vector` certainty pass
  (`certainty = (1 + cosine) / 2`); only hits at/above `similarity_threshold` survive.
  On a small/sparse collection genuine matches can still fall below the default `0.85` —
  lower `course_memory.similarity_threshold` in `application.local.yml` while testing if
  retrieval comes back empty. (Empirical calibration is future work.)
- **Readable channels only.** Retrieval serves only entries from the channels listed in
  `courseMemoryConversationIds` of the run.
- **Public channels only.** Ingestion with `"isPublicChannel": false` is skipped by
  design; Artemis should only emit public-channel events. The field is a **strict**
  boolean — `"true"` or `1` is rejected with a `422` rather than coerced, so a malformed
  payload can never be read as permission to ingest a private thread.

## Configuration reference

`application.local.yml`:

```yaml
course_memory:
  enabled: true
  alpha: 0.5 # hybrid fusion weight (Weaviate convention: 0=BM25/keyword, 1=dense/vector)
  similarity_threshold: 0.85 # min cosine certainty (0-1) for a retrieved entry
  result_limit: 5
  query_rewrite_enabled: true
  context_message_limit: 20

llm_configuration:
  course_memory_ingestion_pipeline:
    default:
      chat: { local: openai/gpt-oss-120b, cloud: azure-gpt-5-mini }
      embedding: Qwen/Qwen3-Embedding-8B
  course_memory_retrieval_pipeline:
    default:
      chat: { local: openai/gpt-oss-120b, cloud: azure-gpt-5-mini }
      embedding: Qwen/Qwen3-Embedding-8B
```
