import json
import threading
from typing import Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter
from weaviate.util import generate_uuid5

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.data.course_memory_dto import (
    CourseMemoryEntryDTO,
    CourseMemorySource,
)
from iris.domain.ingestion.course_memory_ingestion_dto import (
    CourseMemoryIngestionExecutionDTO,
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

# Trigger A sources. THREAD_RESOLVED (Trigger B) is community-resolved only and
# must never overwrite an entry carrying one of these (see upsert()).
TUTOR_VERIFIED_SOURCES = {
    CourseMemorySource.IRIS_AUTO.value,
    CourseMemorySource.TUTOR_WRITTEN.value,
    CourseMemorySource.IRIS_CORRECTED.value,
}

# In-process coordination between the ingestion and deletion workers, which run
# in independent background threads. Without it, a delete that arrives while an
# ingestion is still extracting can complete first, and the older ingestion then
# re-inserts the just-deleted entry. We track a per-key delete counter: ingestion
# snapshots it before extraction and, under the lock, refuses to write if a delete
# bumped it in the meantime. NOTE: in-process only — a multi-replica Pyris
# deployment would need a durable tombstone/version store instead.
_write_coordination_lock = threading.Lock()
_delete_generation: Dict[str, int] = {}


def _current_delete_generation(obj_uuid: str) -> int:
    with _write_coordination_lock:
        return _delete_generation.get(obj_uuid, 0)


def _truncate(text: str, limit: int = 160) -> str:
    """Shorten text for log lines; answers routinely run to several paragraphs."""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


class CourseMemoryIngestionPipeline(AbstractIngestion, Pipeline):
    """Ingests verified Q/A pairs into the CourseMemory collection.

    Runs an LLM extraction over the full thread to produce a canonical
    question/answer pair, embeds only the question, and upserts keyed on
    ``postId`` so tutor corrections and additional resolving answers overwrite
    the thread's existing entry in place.
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

    @classmethod
    def delete_generation_for(cls, post_id: str, course_id: int) -> int:
        """Current delete counter for a thread, for sampling at webhook accept time.

        The webhook returns 202 and hands the work to a background thread, so a
        delete accepted later can still run first. Sampling the counter when the
        request is *accepted* — rather than when the worker happens to be
        scheduled — makes the ordering follow the requests, not the scheduler.
        """
        return _current_delete_generation(cls._deterministic_uuid(post_id, course_id))

    @observe(name="Course Memory Ingestion Pipeline")
    def __call__(self, start_delete_gen: Optional[int] = None) -> bool:
        """Run the ingestion.

        ``start_delete_gen`` is the delete counter sampled by the caller when the
        request was accepted; omitted, it is sampled here instead.
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

            # Snapshot the delete counter before the slow extraction so a delete
            # arriving during it can be detected at write time (see upsert).
            if start_delete_gen is None:
                obj_uuid = self._deterministic_uuid(
                    self.dto.post_id, self.dto.course_id
                )
                start_delete_gen = _current_delete_generation(obj_uuid)

            self.callback.update()
            question, answer = self.extract_qa()
            # Makes the merge of several resolvesPost messages observable without
            # querying Weaviate.
            logger.info(
                "Course memory extraction for thread %s produced question=%r answer=%r",
                self.dto.post_id,
                _truncate(question),
                _truncate(answer),
            )

            self.callback.update()
            self.upsert(question, answer, start_delete_gen=start_delete_gen)
            self.callback.finish(tokens=self.tokens)
            logger.info(
                "Course memory ingestion finished for thread %s (triggered by message %s)",
                self.dto.post_id,
                self.dto.message_id,
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
        """Extract the canonical question and verified answer from the thread.

        For corrections (``IRIS_CORRECTED`` with an ``existing_answer`` provided),
        the supplied tutor-edited answer is used directly and only the question is
        derived from the thread.
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

        is_correction = (
            self.dto.source == CourseMemorySource.IRIS_CORRECTED
            and self.dto.existing_answer
        )
        try:
            question, extracted_answer = self._parse_extraction(response)
        except ValueError:
            # For corrections the tutor's answer is already at hand — don't fail
            # the whole correction on a malformed extraction; fall back to the
            # thread's root post as a best-effort question.
            root_question = self._root_post_content()
            if is_correction and root_question:
                logger.warning(
                    "Q/A extraction unparseable for correction on message %s; "
                    "falling back to the thread root post as the question",
                    self.dto.message_id,
                )
                return root_question, self.dto.existing_answer
            raise

        if is_correction:
            return question, self.dto.existing_answer

        return question, extracted_answer

    def _root_post_content(self) -> str:
        """Content of the thread's first message (the original question), if any."""
        if self.dto.thread and self.dto.thread[0].content:
            return self.dto.thread[0].content.strip()
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

    # Tag applied to every message Artemis flagged as verified/resolving, so the
    # extractor knows which messages to synthesize the answer from.
    VERIFIED_ANSWER_TAG = "VERIFIED ANSWER"

    @staticmethod
    def _is_verified(message) -> bool:
        """Whether Artemis flagged this message as (part of) the verified answer.

        Stated explicitly by the sender — never inferred from ``id``. Artemis
        draws post and answer ids from two tables with independent sequences, so
        a root post and one of its answers routinely share a number; matching on
        it used to tag the student's question as the verified answer.
        """
        return message.is_verified_answer or message.resolves_post

    def _format_thread(self) -> str:
        """Render the thread as an ordered, role-tagged transcript.

        Every flagged message is tagged as a verified answer so the extractor can
        pick them out among ordinary replies. On long threads only
        ``context_message_limit`` messages are kept, but the root post (the
        original question) and all flagged messages are always retained.

        Messages whose author opted out of AI keep their slot but carry the shared
        placeholder instead of their text, so the transcript still reads in order
        without their words ever reaching the model.
        """
        thread = self._truncate_thread(self.dto.thread)
        lines = []
        for message in thread:
            role = message.author_role or "unknown"
            if message.is_iris_draft:
                role = f"{role} (iris draft)"
            marker = (
                f" — {self.VERIFIED_ANSWER_TAG}" if self._is_verified(message) else ""
            )
            content = (
                REDACTED_ANSWER_PLACEHOLDER if message.redacted else message.content
            )
            lines.append(f"[{role}{marker}]: {content}")
        return "\n".join(lines)

    def _truncate_thread(self, thread):
        """Cap the thread at ``context_message_limit`` messages.

        Always keeps the root post and every flagged message; the rest of the
        budget is filled from the most recent tail. Returns the original thread
        unchanged when no limit applies. Note the flagged messages are kept even
        if they alone exceed the limit — dropping one would silently discard part
        of the verified answer.
        """
        limit = settings.course_memory.context_message_limit
        if not limit or limit <= 0 or limit >= len(thread):
            return thread
        keep = {0}
        for i, message in enumerate(thread):
            if self._is_verified(message):
                keep.add(i)
        for i in range(len(thread) - 1, -1, -1):
            if len(keep) >= limit:
                break
            keep.add(i)
        return [thread[i] for i in sorted(keep)]

    @staticmethod
    def _deterministic_uuid(post_id: str, course_id: int) -> str:
        """Stable UUID for a (course, thread) pair, enabling upsert/dedup.

        Keyed on the thread root rather than the answer message so a thread with
        several resolving answers — or one whose answer is later corrected —
        yields a single canonical entry instead of near-duplicates competing in
        hybrid search.
        """
        return generate_uuid5(f"{course_id}:{post_id}")

    def upsert(
        self, question: str, answer: str, start_delete_gen: Optional[int] = None
    ):
        """Embed the question and insert/replace the entry keyed on postId.

        ``start_delete_gen`` is the delete counter snapshot taken before
        extraction; if a deletion bumped it since, the write is skipped so a
        concurrent delete is not undone by this now-stale ingestion.
        """
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
            verified_by=self.dto.verified_by,
        )
        obj_uuid = self._deterministic_uuid(self.dto.post_id, self.dto.course_id)
        props = entry.to_properties()
        # Outer lock serialises this write against a concurrent delete of the
        # same key; inner batch lock is the shared Weaviate write guard.
        with _write_coordination_lock:
            if (
                start_delete_gen is not None
                and _delete_generation.get(obj_uuid, 0) != start_delete_gen
            ):
                logger.info(
                    "Skipping course memory write for thread %s: an entry "
                    "deletion occurred during ingestion",
                    self.dto.post_id,
                )
                return
            with batch_update_lock:
                if self.collection.data.exists(obj_uuid):
                    if self._would_downgrade_provenance(obj_uuid):
                        logger.info(
                            "Keeping tutor-verified course memory for thread %s; "
                            "ignoring THREAD_RESOLVED re-ingestion",
                            self.dto.post_id,
                        )
                        return
                    self.collection.data.replace(
                        uuid=obj_uuid, properties=props, vector=vec
                    )
                    logger.info(
                        "Replaced course memory entry for thread %s (source=%s)",
                        self.dto.post_id,
                        self.dto.source.value,
                    )
                else:
                    self.collection.data.insert(
                        uuid=obj_uuid, properties=props, vector=vec
                    )
                    logger.info(
                        "Inserted course memory entry for thread %s (source=%s)",
                        self.dto.post_id,
                        self.dto.source.value,
                    )

    def _would_downgrade_provenance(self, obj_uuid: str) -> bool:
        """True when a Trigger B write would overwrite a tutor-verified entry.

        Triggers A and B can both fire for the same answer message; the writer
        must guarantee the trust tier never drops (and a tutor's exact wording
        is never replaced by an LLM re-extraction). Tutor-sourced writes always
        win, including tutor-over-tutor updates.
        """
        if self.dto.source != CourseMemorySource.THREAD_RESOLVED:
            return False
        existing = self.collection.query.fetch_object_by_id(obj_uuid)
        if existing is None:
            return False
        existing_source = existing.properties.get(CourseMemorySchema.SOURCE.value)
        return existing_source in TUTOR_VERIFIED_SOURCES

    def delete_for_thread(self, post_id: str, course_id: int) -> bool:
        """Delete the entry for a given (course, thread) pair.

        Called when the thread stops being resolved in Artemis — the resolving
        answer was un-marked or deleted, or the thread itself was removed.

        Bumps the per-key delete counter under the coordination lock so an
        ingestion that began before this delete cannot resurrect the entry.
        """
        obj_uuid = self._deterministic_uuid(post_id, course_id)
        try:
            with _write_coordination_lock:
                _delete_generation[obj_uuid] = _delete_generation.get(obj_uuid, 0) + 1
                self.collection.data.delete_by_id(obj_uuid)
            logger.info("Deleted course memory for thread %s", post_id)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("Error deleting course memory: %s", e, exc_info=True)
            return False

    def delete_for_conversation(self, conversation_id: str, course_id: int) -> bool:
        """Delete every entry mined from a channel.

        Called when the channel is deleted in Artemis or stops being public. Channel
        eligibility is only checked when an entry is written, so without this an entry
        would keep being served after its source stopped being readable by the course.

        Unlike :meth:`delete_for_thread` this cannot bump the per-key delete counters:
        the keys are not known up front, and an ingestion already in flight for one of
        those threads may still land afterwards. Deleting a channel is a rare
        administrative action and Artemis stops emitting ingestions for it at the same
        moment, so the window is small; re-running the deletion clears any straggler.
        """
        try:
            with _write_coordination_lock, batch_update_lock:
                result = self.collection.data.delete_many(
                    where=Filter.by_property(
                        CourseMemorySchema.CONVERSATION_ID.value
                    ).equal(conversation_id)
                    & Filter.by_property(CourseMemorySchema.COURSE_ID.value).equal(
                        course_id
                    )
                )
            logger.info(
                "Deleted %s course memory entries for channel %s in course %s",
                getattr(result, "successful", "?"),
                conversation_id,
                course_id,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Error deleting course memory for channel %s: %s",
                conversation_id,
                e,
                exc_info=True,
            )
            return False

    def chunk_data(self, path: str) -> List[Dict[str, str]]:
        """Not applicable: course memory entries are not chunked."""
        return []
