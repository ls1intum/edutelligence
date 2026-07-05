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
from ..vector_database.database import batch_update_lock
from ..vector_database.faq_schema import FaqSchema, init_faq_schema
from ..web.status.faq_ingestion_status_callback import FaqIngestionStatus
from . import Pipeline

logger = get_logger(__name__)


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
            if not self.delete_faq(
                self.dto.faq.faq_id,
                self.dto.faq.course_id,
            ):
                raise RuntimeError("Failed to delete existing FAQ")
            self.callback.update()
            self.callback.update()
            self.batch_update(self.dto.faq)
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

    def batch_update(self, faq: FaqDTO):
        """
        Batch update the faq into the database
        This method is thread-safe and can only be executed by one thread at a time.
        Weaviate limitation.
        """
        with batch_update_lock:
            with self.collection.batch.rate_limit(requests_per_minute=600) as batch:
                try:
                    embed_chunk = self.llm_embedding.embed(
                        f"{faq.question_title} : {faq.question_answer}"
                    )
                    faq_dict = faq.model_dump()

                    batch.add_object(properties=faq_dict, vector=embed_chunk)

                except Exception as e:
                    logger.error("Error updating faq: %s", e)
                    raise

    def delete_old_faqs(self, faqs: list[FaqDTO]):
        """
        Delete the faq from the database
        """
        try:
            for faq in faqs:
                if self.delete_faq(faq.faq_id, faq.course_id):
                    logger.info("Faq deleted successfully")
                else:
                    logger.error("Failed to delete faq")
            self.callback.finish()
        except Exception as e:
            logger.error("Error deleting faqs: %s", e)
            self.callback.fail("Error while removing old faqs")
            return False

    def delete_faq(self, faq_id, course_id):
        """
        Delete the faq from the database
        """
        try:
            self.collection.data.delete_many(
                where=Filter.by_property(FaqSchema.FAQ_ID.value).equal(faq_id)
                & Filter.by_property(FaqSchema.COURSE_ID.value).equal(course_id)
            )
            logger.info("successfully deleted faq with id %s", faq_id)
            return True
        except Exception as e:
            logger.error("Error deleting faq: %s", e, exc_info=True)
            return False

    def chunk_data(self, path: str) -> List[Dict[str, str]]:
        """
        Faqs are so small, they do not need to be chunked into smaller parts
        """
        return
