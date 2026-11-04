from abc import ABC, abstractmethod
from typing import List, Optional

from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import resolve_model
from iris.tracing import observe

from ..pipeline.sub_pipeline import SubPipeline

logger = get_logger(__name__)


class BaseRetrieval(SubPipeline, ABC):
    """
    Base class for retrieval pipelines.
    """

    tokens: List[TokenUsageDTO]

    @abstractmethod
    def __call__(self, *args, **kwargs):
        """Muss in der konkreten Implementierung überschrieben werden"""

    def __init__(self, client: WeaviateClient, schema_init_func, **kwargs):
        super().__init__(
            implementation_id=kwargs.get("implementation_id", "base_retrieval_pipeline")
        )
        pipeline_id = self.implementation_id or "base_retrieval_pipeline"
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=False
        )
        self.llm_embedding = LlmRequestHandler(embedding_model)
        self.collection = schema_init_func(client)
        self.tokens = []

    @observe(name="Retrieval: Search in DB")
    def search_in_db(
        self,
        query: str,
        hybrid_factor: float,
        result_limit: int,
        schema_properties: List[str],
        course_id: Optional[int] = None,
        base_url: Optional[str] = None,
        course_id_property: str = "course_id",
        base_url_property: str = "base_url",
    ):
        """
        Search the database for the given query.
        """
        logger.info("[BASIC_RETRIEVAL] Searching in the database for query: %s", query)
        filter_weaviate = None

        if course_id:
            filter_weaviate = Filter.by_property(course_id_property).equal(course_id)
            if base_url:
                filter_weaviate &= Filter.by_property(base_url_property).equal(base_url)

        vec = self.llm_embedding.embed(query)
        return self.collection.query.hybrid(
            query=query,
            alpha=hybrid_factor,
            vector=vec,
            return_properties=schema_properties,
            limit=result_limit,
            filters=filter_weaviate,
        )

    @abstractmethod
    def get_schema_properties(self) -> List[str]:
        """
        Abstract method to be implemented by subclasses to return the schema properties.
        """
        raise NotImplementedError
