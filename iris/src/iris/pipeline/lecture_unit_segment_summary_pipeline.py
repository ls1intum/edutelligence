from typing import Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.prompts.lecture_unit_segment_summary_prompt import (
    lecture_unit_segment_summary_prompt,
)
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe
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
    ) -> None:
        super().__init__()
        self.weaviate_client = client
        self.lecture_unit_dto = lecture_unit_dto

        self.lecture_unit_segment_collection = init_lecture_unit_segment_schema(client)
        self.lecture_transcription_collection = init_lecture_transcription_schema(
            client
        )
        self.lecture_unit_page_chunk_collection = init_lecture_unit_page_chunk_schema(
            client
        )

        self.llm_embedding = ModelVersionRequestHandler("text-embedding-3-small")

        request_handler = ModelVersionRequestHandler(
            version="gpt-oss:120b" if local else "gpt-4.1-mini"
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    @observe(name="Lecture Unit Segment Summary Pipeline")
    def __call__(self) -> [str]:
        slide_number_start, slide_number_end = self._get_slide_range()

        summaries = []
        for slide_index in range(slide_number_start, slide_number_end + 1):
            transcriptions = self._get_transcriptions(slide_index)
            slides = self._get_slides(slide_index)
            summary = self._create_summary(transcriptions, slides)
            summaries.append(summary)
            self._upsert_lecture_object(slide_index, summary)
        return summaries, self.tokens

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

    def _upsert_lecture_object(self, slide_number: int, summary: str):
        lecture_filter = Filter.by_property(
            LectureUnitSegmentSchema.COURSE_ID.value
        ).equal(self.lecture_unit_dto.course_id)
        lecture_filter &= Filter.by_property(
            LectureUnitSegmentSchema.LECTURE_ID.value
        ).equal(self.lecture_unit_dto.lecture_id)
        lecture_filter &= Filter.by_property(
            LectureUnitSegmentSchema.LECTURE_UNIT_ID.value
        ).equal(self.lecture_unit_dto.lecture_unit_id)
        lecture_filter &= Filter.by_property(
            LectureUnitSegmentSchema.PAGE_NUMBER.value
        ).equal(slide_number)
        if self.lecture_unit_dto.base_url is not None:
            lecture_filter &= Filter.by_property(
                LectureUnitSegmentSchema.BASE_URL.value
            ).equal(self.lecture_unit_dto.base_url)

        lectures = self.lecture_unit_segment_collection.query.fetch_objects(
            filters=lecture_filter, limit=1
        ).objects

        # transcriptions = self._get_transcriptions(slide_number)
        # slides = self._get_slides(slide_number)

        if len(lectures) == 0:
            # Insert new lecture
            self.lecture_unit_segment_collection.data.insert(
                properties={
                    LectureUnitSegmentSchema.COURSE_ID.value: self.lecture_unit_dto.course_id,
                    LectureUnitSegmentSchema.LECTURE_ID.value: self.lecture_unit_dto.lecture_id,
                    LectureUnitSegmentSchema.LECTURE_UNIT_ID.value: self.lecture_unit_dto.lecture_unit_id,
                    LectureUnitSegmentSchema.SEGMENT_SUMMARY.value: summary,
                    LectureUnitSegmentSchema.PAGE_NUMBER.value: slide_number,
                    LectureUnitSegmentSchema.BASE_URL.value: self.lecture_unit_dto.base_url,
                },
                vector=self.llm_embedding.embed(summary),
            )
            # lecture = self.lecture_unit_segment_collection.query
            # .fetch_objects(filters=lecture_filter, limit=1).objects[0]
            # transcription_references = []
            # for transcription in transcriptions.objects:
            #     transcription_reference = DataReference(
            #         from_uuid=lecture.objects[0].uuid.int,
            #         from_property=LectureUnitSegmentSchema.value,
            #         to_uuid=transcription.uuid.int
            #     )
            #     transcription_references.append(transcription_reference)
            # slide_references = []
            # for slide in slides.objects:
            #     slide_reference = DataReference(
            #         from_uuid=lecture.objects[0].uuid.int,
            #         from_property=LectureUnitSegmentSchema.SLIDES.value,
            #         to_uuid=slide.uuid.int
            #     )
            #     slide_references.append(slide_reference)
            #
            # self.lecture_unit_segment_collection.data.reference_add_many(transcription_references)
            # self.lecture_unit_segment_collection.data.reference_add_many(slide_references)
            return

        # Update existing lecture
        # transcription_uuids = [t.uuid for t in transcriptions]
        # slide_uuids = [s.uuid for s in slides]
        lecture_uuid = lectures[0].uuid

        self.lecture_unit_segment_collection.data.update(
            uuid=lecture_uuid,
            properties={
                LectureUnitSegmentSchema.SEGMENT_SUMMARY.value: summary,
            },
            vector=self.llm_embedding.embed(summary),
        )

        # self.lecture_unit_segment_collection.data.reference_replace(
        #     from_uuid=lecture_uuid,
        #     from_property=LectureUnitSegmentSchema.TRANSCRIPTIONS.value,
        #     to=transcription_uuids
        # )
        #
        # self.lecture_unit_segment_collection.data.reference_replace(
        #     from_uuid=lecture_uuid,
        #     from_property=LectureUnitSegmentSchema.SLIDES.value,
        #     to=slide_uuids
        # )
