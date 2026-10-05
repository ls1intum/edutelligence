import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.util import generate_uuid5

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.data.course_memory_dto import (
    TUTOR_VERIFIED_SOURCES,
    VERBATIM_ANSWER_SOURCES,
    CourseMemoryEntryDTO,
    CourseMemorySource,
)
from iris.domain.ingestion.course_memory_ingestion_dto import (
    CourseMemoryIngestionExecutionDTO,
)
from iris.domain.ingestion.course_memory_sync_dto import (
    CourseMemoryCourseSyncDTO,
    CourseMemoryInstanceSyncDTO,
)

from ..common.pipeline_enum import PipelineEnum
from ..domain.variant.variant import Variant
from ..ingestion.abstract_ingestion import AbstractIngestion
from ..llm import CompletionArguments, LlmRequestHandler
from ..llm.langchain import IrisLangchainChatModel
from ..llm.llm_configuration import LlmConfigurationError, resolve_model
from ..pipeline.prompts.course_memory_prompts import (
    course_memory_extraction_system_prompt,
)
from ..pipeline.shared.utils import REDACTED_ANSWER_PLACEHOLDER
from ..tracing import observe
from ..vector_database.course_memory_schema import (
    CourseMemorySchema,
    init_course_memory_schema,
)
from ..vector_database.database import batch_update_lock
from ..web.status.course_memory_ingestion_status_callback import (
    CourseMemoryIngestionStatus,
)
from . import Pipeline

logger = get_logger(__name__)

# The tutor-verified sources as enum members, matching ``dto.source``.
TUTOR_VERIFIED_SOURCE_ENUMS = frozenset(
    CourseMemorySource(value) for value in TUTOR_VERIFIED_SOURCES
)

# Ordering of the operations on one thread is decided by Artemis, not here. Every
# ingestion and every retraction carries a monotonic per-thread ``version``; the stored
# object keeps the highest one it has seen and anything older is ignored. A retraction
# does not remove the object but turns it into a tombstone (``deleted=True``) that keeps
# its version, so an ingestion accepted before the retraction — however late its
# extraction finishes, and whichever order the webhooks arrived in — finds a newer
# version and gives up instead of re-inserting the retracted answer into an empty slot.
# The same rule orders two ingestions: an older extraction can no longer overwrite the
# entry a newer edit produced. Tombstones are never removed, which is what keeps this
# guarantee: nothing in Iris deletes objects in bulk.
#
# Compare-and-write happens under this lock, which makes it atomic against a concurrent
# operation on the same key within this process. Exactly one Iris process may write the
# collection (see COURSE_MEMORY_ARTEMIS_INTEGRATION.md): the lock does not reach across
# processes.
_write_coordination_lock = threading.Lock()

# Objects written this shortly before the snapshot Artemis based a sync on are left alone
# by the sync, to absorb clock skew between Artemis and Iris.
_SYNC_CLOCK_MARGIN = timedelta(minutes=5)

# The version Artemis uses for a thread that no longer exists; also used here for entries
# of deleted courses. Nothing can follow it.
FINAL_VERSION = 2**63 - 1


def _deterministic_uuid(base_url: str, post_id: str, course_id: int) -> str:
    """Stable UUID for an (instance, course, thread) triple, enabling upsert/dedup.

    Keyed on the thread root rather than the answer message so a thread with several
    resolving answers — or one whose answer is later corrected — yields a single
    canonical entry. The instance is part of the key because several Artemis instances
    may share this collection with overlapping course and post ids.
    """
    return generate_uuid5(f"{base_url}|{course_id}|{post_id}")


def _stored_version(obj) -> int:
    """Version recorded on a fetched object; 0 when there is no object."""
    if obj is None:
        return 0
    return int(obj.properties.get(CourseMemorySchema.VERSION.value) or 0)


def _is_tombstone(obj) -> bool:
    return obj is not None and bool(
        obj.properties.get(CourseMemorySchema.DELETED.value)
    )


def _tombstone_properties(
    existing, base_url: str, post_id: str, course_id: int, version: int
) -> dict:
    """Properties of a retracted entry: no content, only the keys and the version."""
    previous = existing.properties if existing is not None else {}
    return {
        CourseMemorySchema.QUESTION.value: "",
        CourseMemorySchema.ANSWER.value: "",
        CourseMemorySchema.COURSE_ID.value: course_id,
        CourseMemorySchema.POST_ID.value: post_id,
        CourseMemorySchema.MESSAGE_ID.value: "",
        CourseMemorySchema.CONVERSATION_ID.value: previous.get(
            CourseMemorySchema.CONVERSATION_ID.value
        )
        or "",
        CourseMemorySchema.SOURCE.value: "",
        CourseMemorySchema.VERIFIED_AT.value: "",
        CourseMemorySchema.VERSION.value: version,
        CourseMemorySchema.DELETED.value: True,
        CourseMemorySchema.BASE_URL.value: base_url,
        CourseMemorySchema.WRITTEN_AT.value: datetime.now(timezone.utc),
    }


def _truncate(text: str, limit: int = 160) -> str:
    """Shorten text for log lines; answers routinely run to several paragraphs."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _as_utc(value) -> Optional[datetime]:
    """A stored ``written_at`` as an aware datetime, or None when absent."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class CourseMemoryDeleter:
    """Retracts Course Memory entries and reconciles them with Artemis.

    Deliberately separate from :class:`CourseMemoryIngestionPipeline` and holding
    nothing but the Weaviate collection. Retraction is the half of this feature that
    must not depend on an LLM being reachable: building the ingestion pipeline resolves
    both a chat and an embedding model, so on a deployment where those are missing or
    misconfigured, ingestion would keep working while every delete failed. Deleting
    resolves no model at all.
    """

    def __init__(self, client: WeaviateClient):
        self.collection = init_course_memory_schema(client)

    @classmethod
    def for_collection(cls, collection) -> "CourseMemoryDeleter":
        """Build a deleter around an already-initialised collection."""
        deleter = object.__new__(cls)
        deleter.collection = collection
        return deleter

    def delete_for_thread(
        self, base_url: str, post_id: str, course_id: int, version: int
    ) -> bool:
        """Retract the entry of a thread by writing a tombstone with ``version``.

        An ingestion of the same thread that was accepted earlier but finishes later
        finds a newer version and is dropped, instead of re-inserting the retracted
        answer into an empty slot. A retraction that is itself older than the stored
        state is ignored: Artemis has since re-resolved the thread, and that newer state
        wins. Equal versions apply the retraction, so a thread deletion that raced the
        last ingestion still ends up retracted. A later re-resolution with a higher
        version overwrites the tombstone in place.
        """
        obj_uuid = _deterministic_uuid(base_url, post_id, course_id)
        try:
            with _write_coordination_lock, batch_update_lock:
                existing = self.collection.query.fetch_object_by_id(obj_uuid)
                stored_version = _stored_version(existing)
                if existing is not None and stored_version > version:
                    logger.info(
                        "Ignoring stale course memory retraction for thread %s: "
                        "version %s is older than the stored version %s",
                        post_id,
                        version,
                        stored_version,
                    )
                    return True
                tombstone = _tombstone_properties(
                    existing, base_url, post_id, course_id, version
                )
                if existing is not None:
                    self.collection.data.replace(uuid=obj_uuid, properties=tombstone)
                else:
                    self.collection.data.insert(uuid=obj_uuid, properties=tombstone)
            logger.info(
                "Retracted course memory for thread %s (version %s)", post_id, version
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("Error deleting course memory: %s", e, exc_info=True)
            return False

    def _objects_of_instance(self, base_url: str):
        """Every object of one Artemis instance (live entries and tombstones).

        The cursor API cannot filter, so this walks the collection once and filters
        here; the collection holds one small object per stored thread.
        """
        properties = [
            CourseMemorySchema.BASE_URL.value,
            CourseMemorySchema.COURSE_ID.value,
            CourseMemorySchema.POST_ID.value,
            CourseMemorySchema.VERSION.value,
            CourseMemorySchema.DELETED.value,
            CourseMemorySchema.WRITTEN_AT.value,
        ]
        for obj in self.collection.iterator(return_properties=properties):
            if obj.properties.get(CourseMemorySchema.BASE_URL.value) == base_url:
                yield obj.properties

    def sync_course(self, dto: CourseMemoryCourseSyncDTO) -> Dict[str, int]:
        """Reconcile the entries of one course with the complete list Artemis sent.

        For every object of the course:

        * thread listed and eligible, stored version >= listed: keep — the latest state
          Artemis dispatched has landed;
        * thread listed and eligible, stored version < listed: an update Artemis already
          dispatched never landed, so the stored text may be outdated (an edit, a deleted
          reply, an author who opted out) — retract at the listed version, which also
          blocks a superseded ingestion that is still running;
        * thread listed but not eligible (channel no longer readable, Iris disabled,
          root post gone): retract at the listed version;
        * thread not listed: the thread was deleted, or it was first resolved after the
          snapshot. Objects written after the snapshot are skipped; older ones are
          retracted at their stored version (a deleted thread can never be minted again).

        Each retraction is a compare-and-write of its own, so the sync never blocks
        ingestion for long and never overwrites a newer write.
        """
        base_url = dto.base_url
        listed = {str(thread.post_id): thread for thread in dto.threads}
        cutoff = dto.snapshot_at.astimezone(timezone.utc) - _SYNC_CLOCK_MARGIN
        counts = {"kept": 0, "retracted": 0, "skipped": 0, "failed": 0}
        for props in list(self._objects_of_instance(base_url)):
            if props.get(CourseMemorySchema.COURSE_ID.value) != dto.course_id:
                continue
            post_id = props.get(CourseMemorySchema.POST_ID.value)
            stored = int(props.get(CourseMemorySchema.VERSION.value) or 0)
            tombstone = bool(props.get(CourseMemorySchema.DELETED.value))
            thread = listed.get(post_id)
            if thread is None:
                written_at = _as_utc(props.get(CourseMemorySchema.WRITTEN_AT.value))
                if tombstone or (written_at is not None and written_at > cutoff):
                    counts["skipped"] += 1
                    continue
                target = stored
            elif not thread.eligible:
                if tombstone and stored >= thread.version:
                    counts["kept"] += 1
                    continue
                target = thread.version
            elif stored >= thread.version:
                counts["kept"] += 1
                continue
            else:
                target = thread.version
            if self.delete_for_thread(base_url, post_id, dto.course_id, target):
                counts["retracted"] += 1
            else:
                counts["failed"] += 1
        logger.info(
            "Course memory sync for course %s finished: %s", dto.course_id, counts
        )
        return counts

    def sync_instance(self, dto: CourseMemoryInstanceSyncDTO) -> Dict[str, int]:
        """Reconcile the courses for which Artemis sends no course sync.

        * course deleted: every object, tombstones included, is raised to the final
          version, so no ingestion that is still running can bring an entry back;
        * course exists but has no thread with a version any more: its live entries are
          treated like unlisted threads in :meth:`sync_course` and retracted at their
          stored version;
        * course with threads: left to its course sync.

        Objects written after the snapshot (minus the clock margin) are skipped.
        """
        base_url = dto.base_url
        existing_courses = set(dto.course_ids)
        courses_with_threads = set(dto.course_ids_with_threads)
        cutoff = dto.snapshot_at.astimezone(timezone.utc) - _SYNC_CLOCK_MARGIN
        counts = {"retracted": 0, "skipped": 0, "failed": 0}
        for props in list(self._objects_of_instance(base_url)):
            course_id = props.get(CourseMemorySchema.COURSE_ID.value)
            if course_id in courses_with_threads:
                continue
            stored = int(props.get(CourseMemorySchema.VERSION.value) or 0)
            tombstone = bool(props.get(CourseMemorySchema.DELETED.value))
            course_deleted = course_id not in existing_courses
            if tombstone and (not course_deleted or stored == FINAL_VERSION):
                continue
            written_at = _as_utc(props.get(CourseMemorySchema.WRITTEN_AT.value))
            if written_at is not None and written_at > cutoff:
                counts["skipped"] += 1
                continue
            post_id = props.get(CourseMemorySchema.POST_ID.value)
            target = FINAL_VERSION if course_deleted else stored
            if self.delete_for_thread(base_url, post_id, course_id, target):
                counts["retracted"] += 1
            else:
                counts["failed"] += 1
        logger.info("Course memory instance sync finished: %s", counts)
        return counts


class CourseMemoryIngestionPipeline(AbstractIngestion, Pipeline):
    """Ingests verified Q/A pairs into the CourseMemory collection.

    Runs an LLM extraction over the full thread to produce a canonical
    question/answer pair, embeds only the question, and upserts keyed on
    ``postId`` so tutor corrections and additional resolving answers overwrite
    the thread's existing entry in place. Writes are ordered by the Artemis
    operation version carried in the payload: the latest state Artemis dispatched
    always wins, whatever order the webhooks were accepted or finished in.
    """

    PIPELINE_ID = "course_memory_ingestion_pipeline"
    ROLES = {"chat", "embedding"}
    VARIANT_DEFS = [
        ("default", "Default", "Default course memory ingestion variant."),
    ]

    def __init__(
        self,
        client: WeaviateClient,
        dto: Optional[CourseMemoryIngestionExecutionDTO],
        callback: CourseMemoryIngestionStatus,
        variant: Variant,
        local: bool = False,
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.client = client
        self.collection = init_course_memory_schema(client)
        self.dto = dto
        self.callback = callback
        # Retrieval (BaseRetrieval) always resolves its embedding with
        # local=False; pin ingestion to the same environment so both sides
        # embed into the same vector space regardless of the LLM selection.
        embedding_model = variant.model("embedding", False)
        chat_model = variant.model("chat", local)
        self._warn_on_embedding_mismatch(embedding_model)
        self.llm_embedding = LlmRequestHandler(embedding_model)
        request_handler = LlmRequestHandler(model_id=chat_model)
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    @staticmethod
    def _warn_on_embedding_mismatch(ingestion_embedding_model: str):
        """Warn when ingestion and retrieval would embed with different models.

        The cosine-certainty gate in retrieval is only meaningful when stored
        and query vectors come from the same embedding model.
        """
        try:
            retrieval_embedding_model = resolve_model(
                "course_memory_retrieval_pipeline", "default", "embedding", local=False
            )
        except LlmConfigurationError:
            return
        if retrieval_embedding_model != ingestion_embedding_model:
            logger.warning(
                "Course memory embedding mismatch: ingestion uses '%s' but "
                "retrieval uses '%s'. Stored and query vectors will live in "
                "different vector spaces, breaking the similarity gate. Align "
                "the 'embedding' entries of course_memory_ingestion_pipeline "
                "and course_memory_retrieval_pipeline in llm_configuration.",
                ingestion_embedding_model,
                retrieval_embedding_model,
            )

    @observe(name="Course Memory Ingestion Pipeline")
    def __call__(self) -> bool:
        """Run the ingestion.

        Ordering against other operations on the same thread rides on the Artemis
        operation version in the payload; nothing needs to be sampled here.
        """
        try:
            # Kill-switch: disabling course memory must stop writes, not just
            # reads. (Deletion stays available so operators can purge entries
            # while the feature is off.)
            if not settings.course_memory.enabled:
                logger.info(
                    "Course memory is disabled, skipping ingestion for thread %s in course %s",
                    self.dto.post_id,
                    self.dto.course_id,
                )
                self.callback.finish()
                return True

            # Only ingest from public channels (req. 5). Defense-in-depth: Artemis
            # should only emit public-channel events.
            if not self.dto.is_public_channel:
                logger.info(
                    "Skipping course memory ingestion for thread %s in course %s: not a public channel",
                    self.dto.post_id,
                    self.dto.course_id,
                )
                self.callback.finish()
                return True

            self.callback.update()
            question, answer = self.extract_qa()
            logger.info(
                "Course memory extraction for thread %s produced question=%r answer=%r",
                self.dto.post_id,
                _truncate(question),
                _truncate(answer),
            )

            self.callback.update()
            self.upsert(question, answer)
            self.callback.finish(tokens=self.tokens)
            logger.info(
                "Course memory ingestion finished for thread %s (triggered by message %s, version %s)",
                self.dto.post_id,
                self.dto.message_id,
                self.dto.version,
            )
            return True
        except Exception as e:
            logger.error("Error ingesting course memory: %s", e, exc_info=True)
            self.callback.fail(
                f"Failed to ingest course memory: {e}",
                exception=e,
                tokens=self.tokens,
            )
            return False

    @observe(name="Course Memory: Q/A Extraction")
    def extract_qa(self) -> Tuple[str, str]:
        """Extract the canonical question and answer from the thread.

        For a tutor-verified source (``IRIS_AUTO``, ``IRIS_CORRECTED``,
        ``TUTOR_WRITTEN``) the DTO carries the exact text the tutor signed off on as
        ``existing_answer``; it is stored verbatim and only the question is derived
        from the thread.
        """
        thread_text = self._format_thread()
        # Pass the transcript as a plain human message, not a prompt template:
        # thread content routinely contains braces (code snippets) that an
        # f-string template would misread as variables and fail on. The system
        # prompt likewise contains a literal JSON example with braces.
        messages = [
            SystemMessage(content=course_memory_extraction_system_prompt),
            HumanMessage(content=thread_text),
        ]
        response = self.pipeline.invoke(messages)
        if self.llm.tokens is not None:
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_COURSE_MEMORY_INGESTION
            )

        has_verbatim_answer = self.dto.source in VERBATIM_ANSWER_SOURCES
        try:
            question, extracted_answer = self._parse_extraction(response)
        except ValueError:
            # With a verbatim answer at hand, don't fail the whole ingestion on a
            # malformed extraction; fall back to the thread's root post as a
            # best-effort question, unless its author opted out.
            root_question = self._root_post_content()
            if has_verbatim_answer and root_question:
                logger.warning(
                    "Q/A extraction unparseable for message %s with a verbatim "
                    "answer; falling back to the thread root post as the question",
                    self.dto.message_id,
                )
                return root_question, self.dto.existing_answer
            raise

        if has_verbatim_answer:
            return question, self.dto.existing_answer

        return question, extracted_answer

    def _root_post_content(self) -> str:
        """Content of the thread's first message (the original question), if usable."""
        if self.dto.thread and not self.dto.thread[0].redacted:
            return (self.dto.thread[0].content or "").strip()
        return ""

    @staticmethod
    def _parse_extraction(response: str) -> Tuple[str, str]:
        """Parse the strict-JSON extraction output defensively."""
        text = response.strip()
        if text.startswith("```"):
            # Strip markdown code fences if the model added them anyway.
            text = text.strip("`")
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
        try:
            data = json.loads(text)
            question = str(data["question"]).strip()
            answer = str(data["answer"]).strip()
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ValueError(
                f"Could not parse Q/A extraction output as JSON: {e}"
            ) from e
        if not question or not answer:
            raise ValueError("Q/A extraction produced an empty question or answer")
        return question, answer

    def _is_answer_source(self, message) -> bool:
        """Whether this message may contribute to the stored answer.

        Stated explicitly by the sender — never inferred from ``id``. For a
        tutor-verified source only the single anchor counts: its trust tier comes from
        the anchor's endorsement alone, so merging another resolving answer (perhaps a
        student's) would pass community content off as tutor-verified. A community
        entry (``THREAD_RESOLVED``) may merge every resolving answer.
        """
        if message.redacted:
            return False
        if self.dto.source in TUTOR_VERIFIED_SOURCE_ENUMS:
            return message.is_verified_answer
        return message.is_verified_answer or message.resolves_post

    def _format_thread(self) -> str:
        """Render the thread as a JSON array of messages.

        JSON rather than tagged lines: every message's content is a JSON string, so no
        message can forge another message, a role or an answer flag by writing one into
        its text. Messages whose author opted out keep their slot but carry the shared
        placeholder instead of their text.
        """
        thread = self._truncate_thread(self.dto.thread)
        messages = []
        for message in thread:
            messages.append(
                {
                    "role": message.author_role or "unknown",
                    "irisDraft": message.is_iris_draft,
                    "answerSource": self._is_answer_source(message),
                    "redacted": message.redacted,
                    "content": (
                        REDACTED_ANSWER_PLACEHOLDER
                        if message.redacted
                        else message.content
                    ),
                }
            )
        return json.dumps(messages, ensure_ascii=False, indent=1)

    def _truncate_thread(self, thread):
        """Cap the thread at ``context_message_limit`` messages.

        Always keeps the root post and every answer-source message; the rest of the
        budget is filled from the most recent tail. Answer-source messages are kept
        even if they alone exceed the limit — dropping one would silently discard part
        of the answer.
        """
        limit = settings.course_memory.context_message_limit
        if not limit or limit <= 0 or limit >= len(thread):
            return thread
        keep = {0}
        for i, message in enumerate(thread):
            if self._is_answer_source(message):
                keep.add(i)
        for i in range(len(thread) - 1, -1, -1):
            if len(keep) >= limit:
                break
            keep.add(i)
        return [thread[i] for i in sorted(keep)]

    def upsert(self, question: str, answer: str):
        """Embed the question and insert/replace the entry keyed on the thread.

        The write is ordered by ``dto.version``: if the stored object — a live entry or
        a tombstone — already carries an equal or higher version, this ingestion is
        stale (a retraction or a newer edit overtook it) and is skipped, so the latest
        state Artemis dispatched always wins. A tombstone with a lower version is
        overwritten: the thread was re-resolved.
        """
        base_url = self.dto.base_url
        vec = self.llm_embedding.embed(question)
        entry = CourseMemoryEntryDTO(
            question=question,
            answer=answer,
            course_id=self.dto.course_id,
            post_id=self.dto.post_id,
            message_id=self.dto.message_id,
            conversation_id=self.dto.conversation_id,
            source=self.dto.source,
            verified_at=self.dto.verified_at,
            version=self.dto.version,
            base_url=base_url,
        )
        obj_uuid = _deterministic_uuid(base_url, self.dto.post_id, self.dto.course_id)
        props = entry.to_properties()
        # Outer lock serialises this write against a concurrent operation on the
        # same key; inner batch lock is the shared Weaviate write guard.
        with _write_coordination_lock, batch_update_lock:
            existing = self.collection.query.fetch_object_by_id(obj_uuid)
            if existing is not None:
                stored_version = _stored_version(existing)
                if stored_version >= self.dto.version:
                    logger.info(
                        "Ignoring stale course memory ingestion for thread %s: "
                        "version %s is not newer than the stored version %s (%s)",
                        self.dto.post_id,
                        self.dto.version,
                        stored_version,
                        "tombstone" if _is_tombstone(existing) else "live entry",
                    )
                    return
                self.collection.data.replace(
                    uuid=obj_uuid, properties=props, vector=vec
                )
                logger.info(
                    "Replaced course memory %s for thread %s (source=%s, "
                    "version %s -> %s)",
                    "tombstone" if _is_tombstone(existing) else "entry",
                    self.dto.post_id,
                    self.dto.source.value,
                    stored_version,
                    self.dto.version,
                )
            else:
                self.collection.data.insert(uuid=obj_uuid, properties=props, vector=vec)
                logger.info(
                    "Inserted course memory entry for thread %s (source=%s, version %s)",
                    self.dto.post_id,
                    self.dto.source.value,
                    self.dto.version,
                )

    def chunk_data(self, path: str) -> List[Dict[str, str]]:
        """Not applicable: course memory entries are not chunked."""
        return []
