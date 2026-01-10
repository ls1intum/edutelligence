from asyncio.log import logger
from typing import Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    FaqIngestionPipelineExecutionDto,
)

from ..domain.data.faq_dto import FaqDTO
from ..domain.variant.faq_ingestion_variant import FaqIngestionVariant
from ..ingestion.abstract_ingestion import AbstractIngestion
from ..llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ..llm.langchain import IrisLangchainChatModel
from ..tracing import observe
from ..vector_database.database import batch_update_lock
from ..vector_database.faq_schema import FaqSchema, init_faq_schema
from ..web.status.faq_ingestion_status_callback import FaqIngestionStatus
from . import Pipeline


class FaqIngestionPipeline(AbstractIngestion, Pipeline[FaqIngestionVariant]):
    """FaqIngestionPipeline handles the ingestion of FAQs into the database.

    It deletes old FAQs, processes new FAQ data using the language model pipeline,
    batches the updates, and reports the ingestion status via a callback.
    """

    def __init__(
        self,
        client: WeaviateClient,
        dto: Optional[FaqIngestionPipelineExecutionDto],
        callback: FaqIngestionStatus,
    ):
        super().__init__()
        self.client = client
        self.collection = init_faq_schema(client)
        self.dto = dto
        self.callback = callback
        self.llm_embedding = ModelVersionRequestHandler("text-embedding-3-small")
        request_handler = ModelVersionRequestHandler(version="gpt-4.1-mini")
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    @classmethod
    def get_variants(cls) -> List[FaqIngestionVariant]:
        """
        Returns available variants for the FaqIngestionPipeline.

        Returns:
            List of FaqIngestionVariant objects representing available variants
        """
        return [
            FaqIngestionVariant(
                variant_id="default",
                name="Default",
                description="Default FAQ ingestion variant using efficient models.",
                chat_model="gpt-4.1-mini",
                embedding_model="text-embedding-3-small",
            )
        ]

    @observe(name="FAQ Ingestion Pipeline")
    def __call__(self) -> bool:
        try:
            self.callback.in_progress("Deleting old faq from database...")
            self.delete_faq(
                self.dto.faq.faq_id,
                self.dto.faq.course_id,
            )
            self.callback.done("Old faq removed")
            self.callback.in_progress("Ingesting faqs into database...")
            self.batch_update(self.dto.faq)
            self.callback.done("Faq Ingestion Finished", tokens=self.tokens)
            logger.info(
                "Faq ingestion pipeline finished Successfully for faq: %s",
                self.dto.faq.faq_id,
            )
            return True
        except Exception as e:
            logger.error("Error updating faq: %s", e)
            self.callback.error(
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
                    self.callback.error(
                        f"Failed to ingest faqs into the database: {e}",
                        exception=e,
                        tokens=self.tokens,
                    )

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
            self.callback.done("Old faqs removed")
        except Exception as e:
            logger.error("Error deleting faqs: %s", e)
            self.callback.error("Error while removing old faqs")
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
