from typing import Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    FaqIngestionPipelineExecutionDto,
)

from ..domain.data.faq_dto import FaqDTO
from ..domain.variant.variant import Variant
from ..ingestion.abstract_ingestion import AbstractIngestion
from ..llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from ..llm.langchain import IrisLangchainChatModel
from ..tracing import observe
from ..vector_database.batch_verify import delete_many_with_retry, fetch_with_retry
from ..vector_database.database import batch_update_lock
from ..vector_database.faq_schema import FaqSchema, init_faq_schema
from ..web.status.faq_ingestion_status_callback import FaqIngestionStatus
from . import Pipeline

logger = get_logger(__name__)

# Far above the rows one FAQ can have; the delete itself matches by identity, so this only bounds
# the scan for other instances' rows
_FAQ_ROW_LIMIT = 1000


class FaqIngestionPipeline(AbstractIngestion, Pipeline):
    """FaqIngestionPipeline handles the ingestion of FAQs into the database.

    It deletes old FAQs, processes new FAQ data using the language model pipeline,
    batches the updates, and reports the ingestion status via a callback.
    """

    PIPELINE_ID = "faq_ingestion_pipeline"
    ROLES = {"chat", "embedding"}
    VARIANT_DEFS = [
        ("default", "Default", "Default FAQ ingestion variant using efficient models."),
    ]

    def __init__(
        self,
        client: WeaviateClient,
        dto: Optional[FaqIngestionPipelineExecutionDto],
        callback: FaqIngestionStatus,
        variant: Variant,
        local: bool = False,
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.client = client
        self.collection = init_faq_schema(client)
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

    @observe(name="FAQ Ingestion Pipeline")
    def __call__(self) -> bool:
        try:
            self.callback.update()
            base_url = self.dto.settings.artemis_base_url if self.dto.settings else None
            # Delete first, then insert: one row per FAQ and instance, which also
            # replaces a legacy row without a base URL
            self.delete_faq(self.dto.faq.faq_id, self.dto.faq.course_id, base_url)
            self.callback.update()
            self.callback.update()
            self.insert_faq(self.dto.faq, base_url)
            self.callback.finish(tokens=self.tokens)
            logger.info(
                "Faq ingestion pipeline finished Successfully for faq: %s",
                self.dto.faq.faq_id,
            )
            return True
        except Exception as e:
            logger.error("Error updating faq: %s", e)
            self.callback.fail(
                f"Failed to faq into the database: {e}",
                exception=e,
                tokens=self.tokens,
            )
            return False

    def insert_faq(self, faq: FaqDTO, base_url: Optional[str]):
        """Write the FAQ as one row.

        A single insert raises when Weaviate rejects the object, so a failed write reaches the
        callback as a failure. The batch API used
        before records failures without raising, which lost FAQs silently. Writes stay serialized,
        like every other ingestion write.
        """
        embedding = self.llm_embedding.embed(
            f"{faq.question_title} : {faq.question_answer}"
        )
        properties = {
            FaqSchema.FAQ_ID.value: faq.faq_id,
            FaqSchema.COURSE_ID.value: faq.course_id,
            FaqSchema.QUESTION_TITLE.value: faq.question_title,
            FaqSchema.QUESTION_ANSWER.value: faq.question_answer,
            FaqSchema.COURSE_NAME.value: faq.course_name,
            FaqSchema.COURSE_DESCRIPTION.value: faq.course_description,
        }
        if base_url:
            properties[FaqSchema.BASE_URL.value] = base_url
        if faq.content_fingerprint:
            properties[FaqSchema.CONTENT_FINGERPRINT.value] = faq.content_fingerprint
        with batch_update_lock:
            self.collection.data.insert(properties=properties, vector=embedding)

    def delete_faq(self, faq_id: int, course_id: int, base_url: Optional[str]) -> bool:
        """Delete the FAQ's rows of this Artemis instance, including legacy rows without a base URL.

        Rows of other instances (a base URL that is set and differs) are kept. The delete matches
        the FAQ's identity minus those rows' ids
        instead of deleting row by row, so it also removes ghost rows that a scan still returns but
        the object store no longer holds; a
        delete by id would silently skip them. Raises when the delete fails, so a caller never
        inserts next to rows it could not remove.

        :return: True once the rows are gone (also when there were none)
        """
        identity = Filter.by_property(FaqSchema.FAQ_ID.value).equal(
            faq_id
        ) & Filter.by_property(FaqSchema.COURSE_ID.value).equal(course_id)
        rows = fetch_with_retry(
            lambda: self.collection.query.fetch_objects(
                filters=identity,
                limit=_FAQ_ROW_LIMIT,
                return_properties=[FaqSchema.BASE_URL.value],
            )
        ).objects
        foreign_uuids = [
            str(row.uuid)
            for row in rows
            if row.properties.get(FaqSchema.BASE_URL.value)
            and base_url
            and row.properties.get(FaqSchema.BASE_URL.value) != base_url
        ]
        where = (
            identity & ~Filter.by_id().contains_any(foreign_uuids)
            if foreign_uuids
            else identity
        )
        delete_many_with_retry(self.collection, where, f"faq {faq_id}")
        logger.info("successfully deleted faq with id %s", faq_id)
        return True

    def chunk_data(self, path: str) -> List[Dict[str, str]]:
        """
        Faqs are so small, they do not need to be chunked into smaller parts
        """
        return
