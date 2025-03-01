from typing import Tuple

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from weaviate.client import WeaviateClient
from weaviate.collections.classes.data import DataReference

from app.common.PipelineEnum import PipelineEnum
from app.llm import BasicRequestHandler, CapabilityRequestHandler, RequirementList, CompletionArguments
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.vector_database.lecture_schema import init_lecture_schema, LectureUnitSegmentSchema
from weaviate.classes.query import Filter

from app.vector_database.lecture_slide_schema import LectureUnitPageChunkSchema, init_lecture_slide_schema
from app.vector_database.lecture_transcription_schema import LectureTranscriptionSchema, \
    init_lecture_transcription_schema
from app.pipeline.prompts.lecture_summary_prompt import lecture_summary_prompt


class LectureSummaryPipeline(Pipeline):
    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate

    def __init__(
        self,
        client: WeaviateClient,
        lecture_id: int,
        course_id: int,
        lecture_unit_id: int,
    ) -> None:
        super().__init__()
        self.client = client
        self.lecture_id = lecture_id
        self.course_id = course_id
        self.lecture_unit_id = lecture_unit_id

        self.lecture_collection = init_lecture_schema(client)
        self.lecture_transcription_collection = init_lecture_transcription_schema(client)
        self.lecture_slide_collection = init_lecture_slide_schema(client)
        
        self.llm_embedding = BasicRequestHandler("embedding-small")

        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
                privacy_compliance=True,
            )
        )
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __call__(self) -> None:
        slide_number_start, slide_number_end = self._get_slide_range()
        for slide_index in range(slide_number_start, slide_number_end):
            transcriptions = self._get_transcriptions(slide_index)
            slides = self._get_slides(slide_index)
            summary = self.create_summary(transcriptions, slides)

            self._upsert_lecture_object(slide_index, summary)


    def _get_transcriptions(self, slide_number: int):
        transcription_filter = self._get_lecture_transcription_filter()
        transcription_filter &= Filter.by_property(LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDE_NUMBER.value).equal(slide_number)
        return self.lecture_transcription_collection.query(filter=transcription_filter)


    def _get_slides(self, slide_number: int):
        slide_filter = self._get_lecture_slide_filter()
        slide_filter &= Filter.by_property(LectureUnitPageChunkSchema.PAGE_NUMBER.value).equal(slide_number)
        return self.lecture_slide_collection.query(filter=slide_filter)

    def _get_slide_range(self) -> Tuple[int, int]:
        slides = self.lecture_slide_collection.query(filter=self._get_lecture_slide_filter())

        if len(slides) != 0:
            slide_numbers = [slide.properties.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value) for slide in slides.objects]
            return min(slide_numbers), max(slide_numbers)

        transcriptions = self.lecture_transcription_collection.query(filter=self._get_lecture_transcription_filter())

        if len(transcriptions) != 0:
            slide_numbers = [transcription.properties.get(LectureTranscriptionSchema.SEGMENT_LECTURE_UNIT_SLIDE_NUMBER.value) for transcription in transcriptions.objects]
            return min(slide_numbers), max(slide_numbers)

        return 0, 0

    def _get_lecture_slide_filter(self):
        slide_filter = Filter.by_property(LectureUnitPageChunkSchema.COURSE_ID.value).equal(self.course_id)
        slide_filter &= Filter.by_property(LectureUnitPageChunkSchema.LECTURE_ID.value).equal(self.lecture_id)
        slide_filter &= Filter.by_property(LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value).equal(self.lecture_unit_id)
        return slide_filter

    def _get_lecture_transcription_filter(self):
        transcription_filter = Filter.by_property(LectureTranscriptionSchema.COURSE_ID.value).equal(self.course_id)
        transcription_filter &= Filter.by_property(LectureTranscriptionSchema.LECTURE_ID.value).equal(self.lecture_id)
        transcription_filter &= Filter.by_property(LectureTranscriptionSchema.LECTURE_UNIT_ID.value).equal(self.lecture_unit_id)
        return transcription_filter

    def _get_lecture_information(self) -> Tuple[str, str, str, str]:
        slides = self.lecture_slide_collection.query(filter=self._get_lecture_slide_filter(), limit=1)
        if len(slides) > 0:
            slide = slides.objects[0].properties
            return slide[LectureUnitPageChunkSchema.COURSE_NAME.value], slide[LectureUnitPageChunkSchema.COURSE_DESCRIPTION.value], slide[LectureUnitPageChunkSchema.COURSE_LANGUAGE.value], slide[LectureUnitPageChunkSchema.LECTURE_NAME.value]

        transcriptions = self.lecture_transcription_collection.query(filter=self._get_lecture_transcription_filter(), limit=1)
        transcription = transcriptions.objects[0].properties
        # TODO: Add course description
        return transcription[LectureTranscriptionSchema.COURSE_NAME.value], "", transcription[LectureTranscriptionSchema.LANGUAGE.value], transcription[LectureTranscriptionSchema.LECTURE_NAME.value]



    def create_summary(self, transcriptions, slides) -> str:
        transcriptions_slide_text = ""
        for transcription in transcriptions.objects:
            transcriptions_slide_text += transcription.properties[LectureTranscriptionSchema.SEGMENT_TEXT.value]

        slide_text = ""
        for slide in slides.objects:
            slide_text += slide.properties[LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value]
        lecture_name, course_name, _, _ = self._get_lecture_information()
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    lecture_summary_prompt (
                        lecture_name,
                        course_name,
                        transcription_content=transcriptions_slide_text,
                        slide_content=slide_text
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
        lecture_filter = Filter.by_property(LectureUnitSegmentSchema.COURSE_ID.value).equal(self.course_id)
        lecture_filter &= Filter.by_property(LectureUnitSegmentSchema.LECTURE_ID.value).equal(self.lecture_id)
        lecture_filter &= Filter.by_property(LectureUnitSegmentSchema.LECTURE_UNIT_ID.value).equal(self.lecture_unit_id)
        lecture_filter &= Filter.by_property(LectureUnitSegmentSchema.SLIDE_NUMBER.value).equal(slide_number)

        lectures = self.lecture_collection.query(filter=lecture_filter, limit=1)

        transcriptions = self._get_transcriptions(slide_number)
        slides = self._get_slides(slide_number)

        if len(lectures) == 0:
            #Insert new lecture
            course_name, course_description, language, lecture_name  = self._get_lecture_information()
            self.lecture_collection.create(
                properties={
                    LectureUnitSegmentSchema.COURSE_ID.value: self.course_id,
                    LectureUnitSegmentSchema.COURSE_NAME.value: course_name,
                    LectureUnitSegmentSchema.COURSE_DESCRIPTION.value: course_description,
                    LectureUnitSegmentSchema.COURSE_LANGUAGE.value: language,
                    LectureUnitSegmentSchema.LECTURE_ID.value: self.lecture_id,
                    LectureUnitSegmentSchema.LECTURE_NAME.value: lecture_name,
                    LectureUnitSegmentSchema.CONTENT.value: summary,
                    LectureUnitSegmentSchema.SLIDE_NUMBER.value: slide_number,
                }
            )
            lecture = self.lecture_collection.query(filter=lecture_filter, limit=1)
            transcription_references = []
            for transcription in transcriptions.objects:
                transcription_reference = DataReference(
                    from_uuid=lecture.objects[0].uuid.int,
                    from_property=LectureUnitSegmentSchema.TRANSCRIPTIONS.value,
                    to_uuid=transcription.uuid.int
                )
                transcription_references.append(transcription_reference)
            slide_references = []
            for slide in slides.objects:
                slide_reference = DataReference(
                    from_uuid=lecture.objects[0].uuid.int,
                    from_property=LectureUnitSegmentSchema.SLIDES.value,
                    to_uuid=slide.uuid.int
                )
                slide_references.append(slide_reference)

            self.lecture_collection.data.reference_add_many(transcription_references)
            self.lecture_collection.data.reference_add_many(slide_references)
            return

        #update existing lecture
        transcription_uuids = [t.uuid.int for t in transcriptions.objects]
        slide_uuids = [s.uuid.int for s in slides.objects]
        lecture_uuid = lectures.objects[0].uuid.int

        self.lecture_collection.update(
            id=lecture_uuid,
            properties={
                LectureUnitSegmentSchema.CONTENT.value: summary,
            }
        )

        self.lecture_collection.data.reference_replace(
            from_uuid=lecture_uuid,
            from_property=LectureUnitSegmentSchema.TRANSCRIPTIONS.value,
            to=transcription_uuids
        )

        self.lecture_collection.data.reference_replace(
            from_uuid=lecture_uuid,
            from_property=LectureUnitSegmentSchema.SLIDES.value,
            to=slide_uuids
        )

