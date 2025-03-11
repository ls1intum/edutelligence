from asyncio.log import logger
from typing import Optional, List, Dict
from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter
from . import Pipeline
from app.vector_database.database import batch_update_lock
from ..domain.data.faq_dto import FaqDTO

from app.domain.ingestion.ingestion_pipeline_execution_dto import (
    FaqIngestionPipelineExecutionDto,
)
from ..llm.langchain import IrisLangchainChatModel
from ..vector_database.faq_schema import FaqSchema, init_faq_schema
from ..ingestion.abstract_ingestion import AbstractIngestion
from ..llm import (
    BasicRequestHandler,
    CompletionArguments,
    CapabilityRequestHandler,
    RequirementList,
)
from ..web.status.faq_ingestion_status_callback import FaqIngestionStatus


class FaqIngestionPipeline(AbstractIngestion, Pipeline):

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
        self.llm_embedding = BasicRequestHandler("embedding-small")
        self.callback = callback
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.25,
                context_length=16385,
                privacy_compliance=True,
            )
        )
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

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
                f"Faq ingestion pipeline finished Successfully for faq: {self.dto.faq.faq_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Error updating faq: {e}")
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
                    logger.error(f"Error updating faq: {e}")
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
            logger.error(f"Error deleting faqs: {e}")
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
            logger.info(f"successfully deleted faq with id {faq_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting faq: {e}", exc_info=True)
            return False

    def chunk_data(self, path: str) -> List[Dict[str, str]]:
        """
        Faqs are so small, they do not need to be chunked into smaller parts
        """
        return
