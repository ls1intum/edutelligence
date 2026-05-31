from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate.classes.query import Filter
from weaviate.client import WeaviateClient

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
from iris.web.status.status_update import StatusCallback


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
        summaries = []
        all_slides = self._get_all_slides()
        transcriptions_by_page_number = self._get_transcriptions_by_page_number()
        slides_by_page_number = {}
        for slide in all_slides:
            page_number = int(
                slide.properties.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value, -1)
            )
            slides_by_page_number.setdefault(page_number, []).append(slide)

        transcription_page_numbers = set(transcriptions_by_page_number.keys())
        slide_display_numbers = set()
        total_segments = len(slides_by_page_number)
        transcription_only_numbers = set()

        if len(slides_by_page_number) != 0:
            for i, page_number in enumerate(sorted(slides_by_page_number.keys())):
                if self.callback is not None:
                    self.callback.in_progress(
                        f"Generating lecture unit summary for slide {page_number} ({i + 1}/{total_segments})"
                    )
                slides = slides_by_page_number[page_number]
                display_page_number = self._get_display_page_number(slides)
                slide_display_numbers.add(display_page_number)
                transcriptions = (
                    []
                    if display_page_number == -1
                    else transcriptions_by_page_number.get(display_page_number, [])
                )
                summary = self._create_summary(transcriptions, slides)
                summaries.append(summary)
                self._upsert_lecture_object(page_number, summary, display_page_number)

            # Keep transcript-only segments for pages that are not represented by
            # slide display numbers. For -1, always keep transcript-only separate.
            transcription_only_numbers = {
                page_number
                for page_number in transcription_page_numbers
                if page_number == -1 or page_number not in slide_display_numbers
            }
        else:
            transcription_only_numbers = transcription_page_numbers

        for i, page_number in enumerate(sorted(transcription_only_numbers)):
            if self.callback is not None:
                current_segment = total_segments + i + 1
                total_with_transcripts = total_segments + len(
                    transcription_only_numbers
                )
                self.callback.in_progress(
                    f"Generating lecture unit summary for transcript page {page_number} "
                    f"({current_segment}/{total_with_transcripts})"
                )
            transcriptions = transcriptions_by_page_number.get(page_number, [])
            summary = self._create_summary(transcriptions, [])
            summaries.append(summary)
            self._upsert_lecture_object(page_number, summary, page_number)

        if len(summaries) == 0:
            summary = self._create_summary([], [])
            summaries.append(summary)
            self._upsert_lecture_object(0, summary, 0)
        return summaries, self.tokens

    def _get_all_slides(self):
        return self.lecture_unit_page_chunk_collection.query.fetch_objects(
            filters=self._get_lecture_slide_filter()
        ).objects

    def _get_display_page_number(self, slides) -> int:
        if len(slides) == 0:
            return -1
        return int(
            slides[0].properties.get(
                LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value, -1
            )
        )

    def _get_transcriptions_by_page_number(self) -> dict[int, list]:
        transcriptions = self.lecture_transcription_collection.query.fetch_objects(
            filters=self._get_lecture_transcription_filter()
        ).objects

        transcriptions_by_page_number = {}
        for transcription in transcriptions:
            page_number = int(
                transcription.properties.get(
                    LectureTranscriptionSchema.PAGE_NUMBER.value
                )
            )
            transcriptions_by_page_number.setdefault(page_number, []).append(
                transcription
            )
        return transcriptions_by_page_number

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

    def _upsert_lecture_object(
        self, slide_number: int, summary: str, display_page_number: int
    ):
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
        lecture_filter &= Filter.by_property(
            LectureUnitSegmentSchema.DISPLAY_PAGE_NUMBER.value
        ).equal(display_page_number)
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
                    LectureUnitSegmentSchema.DISPLAY_PAGE_NUMBER.value: display_page_number,
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
                LectureUnitSegmentSchema.DISPLAY_PAGE_NUMBER.value: display_page_number,
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
