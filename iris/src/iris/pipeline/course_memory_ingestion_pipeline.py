import json
from typing import Dict, List, Optional, Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from weaviate import WeaviateClient
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


class CourseMemoryIngestionPipeline(AbstractIngestion, Pipeline):
    """Ingests verified Q/A pairs into the CourseMemory collection.

    Runs an LLM extraction over the full thread to produce a canonical
    question/answer pair, embeds only the question, and upserts keyed on
    ``messageId`` so tutor corrections overwrite the existing entry in place.
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
        try:
            # Kill-switch: disabling course memory must stop writes, not just
            # reads. (Deletion stays available so operators can purge entries
            # while the feature is off.)
            if not settings.course_memory.enabled:
                logger.info("Course memory is disabled, skipping ingestion")
                self.callback.finish()
                return True

            # Only ingest from public channels (req. 5). Defense-in-depth: Artemis
            # should only emit public-channel events.
            if not self.dto.is_public_channel:
                logger.info("Skipping course memory ingestion for non-public channel")
                self.callback.finish()
                return True

            self.callback.update()
            question, answer = self.extract_qa()

            self.callback.update()
            self.upsert(question, answer)
            self.callback.finish(tokens=self.tokens)
            logger.info(
                "Course memory ingestion finished for message %s",
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
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", course_memory_extraction_system_prompt),
                ("user", thread_text),
            ]
        )
        response = (prompt | self.pipeline).invoke({})
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

    def _format_thread(self) -> str:
        """Render the thread as an ordered, role-tagged transcript.

        On long threads only ``context_message_limit`` messages are kept: the
        root post (which usually holds the original question) plus the most
        recent tail. Pure tail-truncation would drop the question itself.
        """
        limit = settings.course_memory.context_message_limit
        thread = self.dto.thread
        if limit and 0 < limit < len(thread):
            tail_start = len(thread) - (limit - 1)
            thread = [thread[0]] + thread[tail_start:]
        lines = []
        for message in thread:
            role = message.author_role or "unknown"
            if message.is_iris_draft:
                role = f"{role} (iris draft)"
            lines.append(f"[{role}]: {message.content}")
        return "\n".join(lines)

    @staticmethod
    def _deterministic_uuid(message_id: str, course_id: int) -> str:
        """Stable UUID for a (course, answer-message) pair, enabling upsert/dedup."""
        return generate_uuid5(f"{course_id}:{message_id}")

    def upsert(self, question: str, answer: str):
        """Embed the question and insert/replace the entry keyed on messageId."""
        vec = self.llm_embedding.embed(question)
        entry = CourseMemoryEntryDTO(
            question=question,
            answer=answer,
            course_id=self.dto.course_id,
            message_id=self.dto.message_id,
            conversation_id=self.dto.conversation_id,
            source=self.dto.source,
            verified_at=self.dto.verified_at,
            verified_by=self.dto.verified_by,
        )
        obj_uuid = self._deterministic_uuid(self.dto.message_id, self.dto.course_id)
        props = entry.to_properties()
        with batch_update_lock:
            if self.collection.data.exists(obj_uuid):
                if self._would_downgrade_provenance(obj_uuid):
                    logger.info(
                        "Keeping tutor-verified course memory for message %s; "
                        "ignoring THREAD_RESOLVED re-ingestion",
                        self.dto.message_id,
                    )
                    return
                self.collection.data.replace(
                    uuid=obj_uuid, properties=props, vector=vec
                )
            else:
                self.collection.data.insert(uuid=obj_uuid, properties=props, vector=vec)

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

    def delete_for_message(self, message_id: str, course_id: int) -> bool:
        """Delete the entry for a given (course, answer-message) pair."""
        try:
            obj_uuid = self._deterministic_uuid(message_id, course_id)
            self.collection.data.delete_by_id(obj_uuid)
            logger.info("Deleted course memory for message %s", message_id)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("Error deleting course memory: %s", e, exc_info=True)
            return False

    def chunk_data(self, path: str) -> List[Dict[str, str]]:
        """Not applicable: course memory entries are not chunked."""
        return []
