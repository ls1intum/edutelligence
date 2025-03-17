import os
from asyncio.log import logger
from enum import Enum
from typing import List, Union

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable

from app.domain.retrieval.lecture.lecture_retrieval_dto import LectureRetrievalDTO
from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.common.PipelineEnum import PipelineEnum
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.vector_database.faq_schema import FaqSchema

from app.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)


class InformationType(str, Enum):
    PARAGRAPHS = "PARAGRAPHS"
    FAQS = "FAQS"


class CitationPipeline(Pipeline):
    """A generic reranker pipeline that can be used to rerank a list of documents based on a question"""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self):
        super().__init__(implementation_id="citation_pipeline")
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.25,
                context_length=16385,
            )
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=CompletionArguments(temperature=0, max_tokens=4000),
        )
        dirname = os.path.dirname(__file__)
        prompt_file_path = os.path.join(dirname, "..", "prompts", "citation_prompt.txt")
        with open(prompt_file_path, "r") as file:
            self.lecture_prompt_str = file.read()
        prompt_file_path = os.path.join(
            dirname, "..", "prompts", "faq_citation_prompt.txt"
        )
        with open(prompt_file_path, "r") as file:
            self.faq_prompt_str = file.read()
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def create_formatted_lecture_string(self, lecture_retrieval_dto: LectureRetrievalDTO):
        """
        Create a formatted string from the data
        """

        print("Lecture string!!!")
        print(f"retireval: {lecture_retrieval_dto}")
        formatted_string_lecture_page_chunks = ""
        for i, paragraph in enumerate(lecture_retrieval_dto.lecture_unit_page_chunks):
            lct = "Lecture Slide: {}, Unit: {}, Page: {}, Link: {},\nContent:\n---{}---\n\n".format(
                paragraph.lecture_name,
                paragraph.attachment_unit_name,
                paragraph.page_number,
                paragraph.attachment_unit_link
                or "No link available",
                paragraph.page_text_content,
            )
            formatted_string_lecture_page_chunks += lct

        formatted_string_lecture_transcriptions = ""

        for i, paragraph in enumerate(lecture_retrieval_dto.lecture_transcriptions):
            lct = "Lecture Transcription: {}, Unit: {}, Page: {}, Link: {}, Start Time: {}, End Time: {},\nContent:\n---{}---\n\n".format(
                paragraph.lecture_name,
                paragraph.video_unit_name,
                paragraph.page_number,
                paragraph.video_unit_link
                or "No link available",
                paragraph.segment_start_time,
                paragraph.segment_end_time,
                paragraph.segment_text
            )
            formatted_string_lecture_transcriptions += lct

        print(f"Formatted string page chunks: {formatted_string_lecture_page_chunks}")
        print(f"Formatted string transcriptions: {formatted_string_lecture_transcriptions}")

        return formatted_string_lecture_page_chunks.replace("{", "{{").replace("}", "}}"), formatted_string_lecture_transcriptions.replace("{", "{{").replace("}", "}}")

    def create_formatted_faq_string(self, faqs, base_url):
        """
        Create a formatted string from the data
        """
        formatted_string = ""
        for i, faq in enumerate(faqs):
            faq = "FAQ ID {}, CourseId {} , FAQ Question title {} and FAQ Question Answer {} and FAQ link {}".format(
                faq.get(FaqSchema.FAQ_ID.value),
                faq.get(FaqSchema.COURSE_ID.value),
                faq.get(FaqSchema.QUESTION_TITLE.value),
                faq.get(FaqSchema.QUESTION_ANSWER.value),
                f"{base_url}/courses/{faq.get(FaqSchema.COURSE_ID.value)}/faq/?faqId={faq.get(FaqSchema.FAQ_ID.value)}",
            )
            formatted_string += faq

        return formatted_string.replace("{", "{{").replace("}", "}}")

    def __call__(
        self,
        information,#: #Union[List[dict], List[str]],
        answer: str,
        information_type: InformationType = InformationType.PARAGRAPHS,
        **kwargs,
    ) -> str:
        """
        Runs the pipeline
            :param information: List of info as list of dicts or strings to augment response
            :param query: The query
            :param information_type: The type of information provided. can be either lectures or faqs
            :return: Selected file content
        """
        paras = ""
        paragraphs_page_chunks = ""
        paragraphs_transcriptions = ""


        print("--------------CITATION PIPELINE CALLED!!! --------------")

        if information_type == InformationType.FAQS:
            paras = self.create_formatted_faq_string(
                information, kwargs.get("base_url")
            )
            self.prompt_str = self.faq_prompt_str
        if information_type == InformationType.PARAGRAPHS:
            paragraphs_page_chunks, paragraphs_transcriptions = self.create_formatted_lecture_string(information)
            self.prompt_str = self.lecture_prompt_str

        try:
            self.default_prompt = PromptTemplate(
                template=self.prompt_str,
                input_variables=["Answer", "Paragraphs"],
            )
            if information_type == InformationType.FAQS:
                print(f"params: {paras}")
                response = (self.default_prompt | self.pipeline).invoke(
                    {"Answer": answer, "Paragraphs": paras}
                )
            else:
                response = (self.default_prompt | self.pipeline).invoke(
                    {"Answer": answer, "Paragraphs": paragraphs_page_chunks, "TranscriptionParagraphs": paragraphs_transcriptions}
                )
            self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
            if response == "!NONE!":
                return answer
            return response
        except Exception as e:
            logger.error("citation pipeline failed", e)
            raise e
