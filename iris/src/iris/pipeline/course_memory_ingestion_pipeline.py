import json
from typing import Dict, List, Optional, Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from weaviate import WeaviateClient
from weaviate.util import generate_uuid5

from iris.common.logging_config import get_logger
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
from ..pipeline.prompts.course_memory_prompts import (
    course_memory_extraction_system_prompt,
)
from ..tracing import observe
from ..vector_database.course_memory_schema import init_course_memory_schema
from ..vector_database.database import batch_update_lock
from ..web.status.course_memory_ingestion_status_callback import (
    CourseMemoryIngestionStatus,
)
from . import Pipeline

logger = get_logger(__name__)


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
        embedding_model = variant.model("embedding", local)
        chat_model = variant.model("chat", local)
        self.llm_embedding = LlmRequestHandler(embedding_model)
        request_handler = LlmRequestHandler(model_id=chat_model)
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    @observe(name="Course Memory Ingestion Pipeline")
    def __call__(self) -> bool:
        try:
            # Only ingest from public channels (req. 5). Defense-in-depth: Artemis
            # should only emit public-channel events.
            if not self.dto.is_public_channel:
                logger.info("Skipping course memory ingestion for non-public channel")
                self.callback.done("Skipped non-public channel", tokens=self.tokens)
                return True

            self.callback.in_progress("Extracting Q/A from thread...")
            question, answer = self.extract_qa()

            self.callback.done("Q/A extracted")
            self.callback.in_progress("Embedding & storing memory...")
            self.upsert(question, answer)
            self.callback.done("Course memory ingestion finished", tokens=self.tokens)
            logger.info(
                "Course memory ingestion finished for message %s",
                self.dto.message_id,
            )
            return True
        except Exception as e:
            logger.error("Error ingesting course memory: %s", e, exc_info=True)
            self.callback.error(
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

        question, extracted_answer = self._parse_extraction(response)

        if (
            self.dto.source == CourseMemorySource.IRIS_CORRECTED
            and self.dto.existing_answer
        ):
            return question, self.dto.existing_answer

        return question, extracted_answer

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
        """Render the thread as an ordered, role-tagged transcript."""
        lines = []
        for message in self.dto.thread:
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
                self.collection.data.replace(
                    uuid=obj_uuid, properties=props, vector=vec
                )
            else:
                self.collection.data.insert(uuid=obj_uuid, properties=props, vector=vec)

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
        return
