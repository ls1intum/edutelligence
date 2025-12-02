from asyncio.log import logger

from langchain_core.output_parsers import StrOutputParser
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureUnitRetrievalDTO,
    LectureUnitSegmentRetrievalDTO,
)
from iris.llm import (
    CompletionArguments,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.request_handler.model_version_request_handler import (
    ModelVersionRequestHandler,
)
from iris.llm.request_handler.rerank_request_handler import (
    RerankRequestHandler,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.vector_database.lecture_unit_schema import (
    LectureUnitSchema,
    init_lecture_unit_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)


class LectureUnitSegmentRetrieval(SubPipeline):
    """LectureUnitSegmentRetrieval retrieves lecture unit segments based on search queries and returns the matching
    results."""

    def __init__(self, client: WeaviateClient):
        super().__init__(implementation_id="lecture_unit_segment_retrieval_pipeline")
        request_handler = ModelVersionRequestHandler(version="gpt-4.1-mini")
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.llm_embedding = ModelVersionRequestHandler(
            version="text-embedding-3-small"
        )
        self.pipeline = self.llm | StrOutputParser()
        self.collection = init_lecture_unit_segment_schema(client)
        self.lecture_unit_collection = init_lecture_unit_schema(client)
        self.cohere_client = RerankRequestHandler(model_id="cohere")
        self.tokens = []

    def __call__(
        self,
        student_query: str,
        rewritten_query: str,
        hypothetical_answer: str,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        result_limit: int = 10,
        hybrid_factor: float = 0.9,
        top_n_reranked_results: int = 7,
    ):
        results_rewritten_query = self.search_in_db(
            lecture_unit_dto, rewritten_query, hybrid_factor, result_limit
        )
        results_hypothetical_answer = self.search_in_db(
            lecture_unit_dto, hypothetical_answer, hybrid_factor, result_limit
        )
        unique = {}
        for segment in results_hypothetical_answer + results_rewritten_query:
            unique[segment.uuid] = segment
        results = list(unique.values())
        lecture_unit_segment_retrieval_dtos = []
        for lecture_unit_segment in results:
            lecture_unit_segment_retrieval_dto = self.generate_retrieval_dtos(
                lecture_unit_segment.properties, str(lecture_unit_segment.uuid)
            )
            if lecture_unit_segment_retrieval_dto is None:
                continue

            lecture_unit_segment_retrieval_dtos.append(
                lecture_unit_segment_retrieval_dto
            )

        reranked_answers = self.cohere_client.rerank(
            query=student_query,
            documents=lecture_unit_segment_retrieval_dtos,
            top_n=top_n_reranked_results,
            content_field_name="segment_summary",
        )

        return reranked_answers

    def search_in_db(
        self,
        lecture_unit_dto: LectureUnitRetrievalDTO,
        query: str,
        hybrid_factor: float,
        result_limit: int,
    ):
        """
        Search the database for the given query.
        """
        logger.info(
            "[LECTURE_UNIT_SEGMENT_RETRIEVAL]: Searching in the database for query: %s",
            query,
        )
        # Initialize filter to None by default
        filter_weaviate = None

        # Check if course_id is provided
        if lecture_unit_dto.course_id is not None:
            # Create a filter for course_id
            filter_weaviate = Filter.by_property(
                LectureUnitSegmentSchema.COURSE_ID.value
            ).equal(lecture_unit_dto.course_id)
        if lecture_unit_dto.lecture_id is not None:
            filter_weaviate = Filter.by_property(
                LectureUnitSegmentSchema.LECTURE_ID.value
            ).equal(lecture_unit_dto.lecture_id)
        if lecture_unit_dto.base_url is not None:
            filter_weaviate = Filter.by_property(
                LectureUnitSegmentSchema.BASE_URL.value
            ).equal(lecture_unit_dto.base_url)

        vec = self.llm_embedding.embed(query)
        return_value = self.collection.query.hybrid(
            query=query,
            alpha=hybrid_factor,
            vector=vec,
            limit=result_limit,
            filters=filter_weaviate,
        )
        return return_value.objects

    def generate_retrieval_dtos(self, lecture_unit_segment, uuid: str):
        lecture_unit_filter = Filter.by_property(
            LectureUnitSchema.COURSE_ID.value
        ).equal(lecture_unit_segment[LectureUnitSegmentSchema.COURSE_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_ID.value
        ).equal(lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_ID.value])
        lecture_unit_filter &= Filter.by_property(
            LectureUnitSchema.LECTURE_UNIT_ID.value
        ).equal(lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_UNIT_ID.value])

        lecture_units = self.lecture_unit_collection.query.fetch_objects(
            filters=lecture_unit_filter
        ).objects
        if len(lecture_units) == 0:
            return None

        lecture_unit = lecture_units[0].properties
        lecture_unit_segment_retrieval_dto = LectureUnitSegmentRetrievalDTO(
            uuid=uuid,
            course_id=lecture_unit_segment[LectureUnitSegmentSchema.COURSE_ID.value],
            course_name=str(lecture_unit[LectureUnitSchema.COURSE_NAME.value]),
            course_description=str(
                lecture_unit[LectureUnitSchema.COURSE_DESCRIPTION.value]
            ),
            lecture_id=lecture_unit_segment[LectureUnitSegmentSchema.LECTURE_ID.value],
            lecture_name=str(lecture_unit[LectureUnitSchema.LECTURE_NAME.value]),
            lecture_unit_id=lecture_unit_segment[
                LectureUnitSegmentSchema.LECTURE_UNIT_ID.value
            ],
            lecture_unit_name=str(
                lecture_unit[LectureUnitSchema.LECTURE_UNIT_NAME.value]
            ),
            lecture_unit_link=str(
                lecture_unit[LectureUnitSchema.LECTURE_UNIT_LINK.value]
            ),
            video_link=str(lecture_unit.get(LectureUnitSchema.VIDEO_LINK.value, "")),
            page_number=lecture_unit_segment[
                LectureUnitSegmentSchema.PAGE_NUMBER.value
            ],
            segment_summary=lecture_unit_segment[
                LectureUnitSegmentSchema.SEGMENT_SUMMARY.value
            ],
            base_url=lecture_unit_segment[LectureUnitSegmentSchema.BASE_URL.value],
        )
        return lecture_unit_segment_retrieval_dto
