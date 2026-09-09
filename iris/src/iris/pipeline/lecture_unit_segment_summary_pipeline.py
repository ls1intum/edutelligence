from typing import Optional, Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient
from weaviate.exceptions import UnexpectedStatusCodeError
from weaviate.util import generate_uuid5

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.lecture_unit_segment_summary_prompt import (
    lecture_unit_segment_summary_prompt,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe
from iris.vector_database.batch_verify import delete_many_with_retry
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
    init_lecture_transcription_schema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
    init_lecture_unit_segment_schema,
)
from iris.vector_database.write_retry import WeaviateWriteRetry
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class LectureUnitSegmentSummaryPipeline(SubPipeline):
    """LectureUnitSegmentSummaryPipeline processes lecture unit segments by summarizing the transcription and slide
     content.

    It combines lecture transcriptions and slide text to generate a summary that is then used for further processing or
     storage.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate

    def __init__(
        self,
        client: WeaviateClient,
        lecture_unit_dto: LectureUnitDTO,
        local: bool = False,
        callback: Optional[StatusCallback] = None,
    ) -> None:
        super().__init__(implementation_id="lecture_unit_segment_summary_pipeline")
        self.weaviate_client = client
        self.lecture_unit_dto = lecture_unit_dto
        self.callback = callback

        self.lecture_unit_segment_collection = init_lecture_unit_segment_schema(client)
        self.lecture_transcription_collection = init_lecture_transcription_schema(
            client
        )
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )

        pipeline_id = "lecture_unit_segment_summary_pipeline"
        embedding_model = resolve_model(
            pipeline_id, "default", "embedding", local=False
        )
        chat_model = resolve_model(pipeline_id, "default", "chat", local=local)

        self.llm_embedding = LlmRequestHandler(embedding_model)

        request_handler = LlmRequestHandler(model_id=chat_model)
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    @observe(name="Lecture Unit Segment Summary Pipeline")
    def __call__(self) -> [str]:
        # One shared retry budget for every segment write and the stale prune.
        self._retry = WeaviateWriteRetry.for_request()
        slide_number_start, slide_number_end = self._get_slide_range()

        summaries = []
        total_slides = slide_number_end - slide_number_start + 1
        for slide_index in range(slide_number_start, slide_number_end + 1):
            if self.callback is not None:
                self.callback.update(
                    stage_name="segment-summaries",
                    stage_progress=slide_index - slide_number_start + 1,
                    stage_total=total_slides,
                )
            transcriptions = self._get_transcriptions(slide_index)
            # PAGE_NUMBER is unique at the PDF page level, but the ingestion pipeline
            # stores one object per page chunk after splitting the page text. That is
            # why this returns a list even though the logical slide/page is unique.
            slides = self._get_slides(slide_index)
            display_page_number = slide_index

            if len(slides) != 0:
                display_page_number = int(
                    slides[0].properties.get(
                        LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value,
                        slide_index,
                    )
                )
                if display_page_number == -1:
                    transcriptions = []
                else:
                    transcriptions = self._get_transcriptions(display_page_number)

            summary = self._create_summary(transcriptions, slides)
            summaries.append(summary)
            hidden_until = (
                slides[0].properties.get(LectureUnitPageChunkSchema.HIDDEN_UNTIL.value)
                if slides
                else None
            )
            self._upsert_lecture_object(
                slide_index, summary, display_page_number, hidden_until
            )
        self._prune_stale_segments(slide_number_start, slide_number_end)
        return summaries, self.tokens

    def _prune_stale_segments(self, slide_number_start: int, slide_number_end: int):
        """Remove segments for slides that no longer exist.

        Segments are upserted per slide, so a unit whose PDF shrank would keep
        summaries for the removed slides forever without this sweep.
        """
        stale_filter = Filter.all_of(
            [
                self._get_segment_unit_filter(),
                Filter.any_of(
                    [
                        Filter.by_property(
                            LectureUnitSegmentSchema.PAGE_NUMBER.value
                        ).less_than(slide_number_start),
                        Filter.by_property(
                            LectureUnitSegmentSchema.PAGE_NUMBER.value
                        ).greater_than(slide_number_end),
                    ]
                ),
            ]
        )
        delete_result = delete_many_with_retry(
            self.lecture_unit_segment_collection,
            stale_filter,
            "stale lecture unit segments",
            retry=getattr(self, "_retry", None),
        )
        if delete_result.matches:
            logger.info(
                "[%s / unit %d] Pruned %d stale segment(s) outside slides %d-%d",
                self.lecture_unit_dto.lecture_name,
                self.lecture_unit_dto.lecture_unit_id,
                delete_result.successful,
                slide_number_start,
                slide_number_end,
            )

    def _get_segment_unit_filter(self):
        segment_filter = Filter.by_property(
            LectureUnitSegmentSchema.COURSE_ID.value
        ).equal(self.lecture_unit_dto.course_id)
        segment_filter &= Filter.by_property(
            LectureUnitSegmentSchema.LECTURE_ID.value
        ).equal(self.lecture_unit_dto.lecture_id)
        segment_filter &= Filter.by_property(
            LectureUnitSegmentSchema.LECTURE_UNIT_ID.value
        ).equal(self.lecture_unit_dto.lecture_unit_id)
        if self.lecture_unit_dto.base_url is not None:
            segment_filter &= Filter.by_property(
                LectureUnitSegmentSchema.BASE_URL.value
            ).equal(self.lecture_unit_dto.base_url)
        return segment_filter

    def _get_transcriptions(self, slide_number: int):
        transcription_filter = self._get_lecture_transcription_filter()
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.PAGE_NUMBER.value
        ).equal(slide_number)
        return self.lecture_transcription_collection.query.fetch_objects(
            filters=transcription_filter
        ).objects

    def _get_slides(self, slide_number: int):
        slide_filter = self._get_lecture_slide_filter()
        slide_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.PAGE_NUMBER.value
        ).equal(slide_number)
        return self.lecture_unit_page_chunk_collection.query.fetch_objects(
            filters=slide_filter
        ).objects

    def _get_slide_range(self) -> Tuple[int, int]:
        slides = self.lecture_unit_page_chunk_collection.query.fetch_objects(
            filters=self._get_lecture_slide_filter()
        ).objects

        if len(slides) != 0:
            slide_numbers = [
                int(slide.properties.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value))
                for slide in slides
            ]
            return min(slide_numbers), max(slide_numbers)

        transcriptions = self.lecture_transcription_collection.query.fetch_objects(
            filters=self._get_lecture_transcription_filter()
        ).objects

        if len(transcriptions) != 0:
            slide_numbers = [
                int(
                    transcription.properties.get(
                        LectureTranscriptionSchema.PAGE_NUMBER.value
                    )
                )
                for transcription in transcriptions
            ]
            return min(slide_numbers), max(slide_numbers)

        return 0, 0

    def _get_lecture_slide_filter(self):
        slide_filter = Filter.by_property(
            LectureUnitPageChunkSchema.COURSE_ID.value
        ).equal(self.lecture_unit_dto.course_id)
        slide_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_ID.value
        ).equal(self.lecture_unit_dto.lecture_id)
        slide_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
        ).equal(self.lecture_unit_dto.lecture_unit_id)
        if self.lecture_unit_dto.base_url is not None:
            slide_filter &= Filter.by_property(
                LectureUnitPageChunkSchema.BASE_URL.value
            ).equal(self.lecture_unit_dto.base_url)
        return slide_filter

    def _get_lecture_transcription_filter(self):
        transcription_filter = Filter.by_property(
            LectureTranscriptionSchema.COURSE_ID.value
        ).equal(self.lecture_unit_dto.course_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.LECTURE_ID.value
        ).equal(self.lecture_unit_dto.lecture_id)
        transcription_filter &= Filter.by_property(
            LectureTranscriptionSchema.LECTURE_UNIT_ID.value
        ).equal(self.lecture_unit_dto.lecture_unit_id)
        if self.lecture_unit_dto.base_url is not None:
            transcription_filter &= Filter.by_property(
                LectureTranscriptionSchema.BASE_URL.value
            ).equal(self.lecture_unit_dto.base_url)
        return transcription_filter

    def _create_summary(self, transcriptions, slides) -> str:
        transcriptions_slide_text = ""
        for transcription in transcriptions:
            transcriptions_slide_text += f"{transcription.properties[LectureTranscriptionSchema.SEGMENT_TEXT.value]}\n"

        slide_text = ""
        for slide in slides:
            slide_text += f"{slide.properties[LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value]}\n"
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    lecture_unit_segment_summary_prompt(
                        self.lecture_unit_dto.lecture_name,
                        self.lecture_unit_dto.course_name,
                        transcription_content=transcriptions_slide_text,
                        slide_content=slide_text,
                    ),
                ),
            ]
        )
        formatted_prompt = self.prompt.format_messages()
        self.prompt = ChatPromptTemplate.from_messages(formatted_prompt)
        try:
            response = (self.prompt | self.pipeline).invoke({})
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_LECTURE_SUMMARY_PIPELINE
            )
            return response
        except Exception as e:
            raise e

    def _segment_uuid(self, slide_number: int) -> str:
        """Deterministic id for a unit's slide segment.

        Deriving the id from the stable identity (base_url, course, lecture,
        unit, slide) makes the write idempotent: a retry after an ambiguous
        timeout — where the server actually committed the insert — replaces the
        same object instead of creating a duplicate row for the slide.
        """
        return generate_uuid5(
            {
                "base_url": self.lecture_unit_dto.base_url,
                "course_id": self.lecture_unit_dto.course_id,
                "lecture_id": self.lecture_unit_dto.lecture_id,
                "lecture_unit_id": self.lecture_unit_dto.lecture_unit_id,
                "page_number": slide_number,
            }
        )

    def _upsert_lecture_object(
        self,
        slide_number: int,
        summary: str,
        display_page_number: int,
        hidden_until=None,
    ):
        retry = getattr(self, "_retry", None) or WeaviateWriteRetry.for_request()
        segment_uuid = self._segment_uuid(slide_number)
        properties = {
            LectureUnitSegmentSchema.COURSE_ID.value: self.lecture_unit_dto.course_id,
            LectureUnitSegmentSchema.LECTURE_ID.value: self.lecture_unit_dto.lecture_id,
            LectureUnitSegmentSchema.LECTURE_UNIT_ID.value: self.lecture_unit_dto.lecture_unit_id,
            LectureUnitSegmentSchema.SEGMENT_SUMMARY.value: summary,
            LectureUnitSegmentSchema.PAGE_NUMBER.value: slide_number,
            LectureUnitSegmentSchema.DISPLAY_PAGE_NUMBER.value: display_page_number,
            LectureUnitSegmentSchema.BASE_URL.value: self.lecture_unit_dto.base_url,
            LectureUnitSegmentSchema.HIDDEN_UNTIL.value: hidden_until,
            LectureUnitSegmentSchema.CONTENT_FINGERPRINT.value: self.lecture_unit_dto.content_fingerprint,
        }
        embedding = self.llm_embedding.embed(summary)

        def upsert():
            # Insert under the deterministic id; if it already exists (a prior
            # attempt landed, or a previous run wrote this slide) replace it in
            # place. Both paths are idempotent, so retrying is duplicate-safe.
            try:
                self.lecture_unit_segment_collection.data.insert(
                    uuid=segment_uuid, properties=properties, vector=embedding
                )
            except UnexpectedStatusCodeError as error:
                if "already exists" in str(error).lower():
                    self.lecture_unit_segment_collection.data.replace(
                        uuid=segment_uuid, properties=properties, vector=embedding
                    )
                else:
                    raise

        retry.run(upsert, description=f"segment upsert slide {slide_number}")
