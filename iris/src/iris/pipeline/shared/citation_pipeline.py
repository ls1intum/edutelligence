import os
from asyncio.log import logger
from enum import Enum

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable

from iris.common.pipeline_enum import PipelineEnum
from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
)
from iris.llm import (
    CompletionArguments,
    GPTVersionRequestHandler,
)
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.vector_database.faq_schema import FaqSchema


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
        request_handler = GPTVersionRequestHandler(version="gpt-4o-mini")
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=CompletionArguments(temperature=0, max_tokens=4000),
        )
        dirname = os.path.dirname(__file__)
        prompt_file_path = os.path.join(dirname, "..", "prompts", "citation_prompt.txt")
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.lecture_prompt_str = file.read()
        prompt_file_path = os.path.join(
            dirname, "..", "prompts", "faq_citation_prompt.txt"
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
            self.faq_prompt_str = file.read()
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def create_formatted_lecture_string(
        self, lecture_retrieval_dto: LectureRetrievalDTO
    ):
        """
        Create a formatted string from the data
        """

        formatted_string_lecture_page_chunks = ""
        for paragraph in lecture_retrieval_dto.lecture_unit_page_chunks:
            lct = (
                f"Lecture: {paragraph.lecture_name},"
                f" Unit: {paragraph.lecture_unit_name},"
                f" Page: {paragraph.page_number},"
                f" Link: {paragraph.lecture_unit_link or "No link available"},"
                f"\nContent:\n---{paragraph.page_text_content}---\n\n"
            )
            formatted_string_lecture_page_chunks += lct

        formatted_string_lecture_transcriptions = ""

        for paragraph in lecture_retrieval_dto.lecture_transcriptions:
            lct = (
                f"Lecture Transcription: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}, Link: {paragraph.lecture_unit_link}, "
                f"Start Time: {paragraph.segment_start_time}, End Time: {paragraph.segment_end_time},\n"
                f"Content:\n"
                f"---{paragraph.segment_text}---\n\n"
            )
            formatted_string_lecture_transcriptions += lct

        return formatted_string_lecture_page_chunks.replace("{", "{{").replace(
            "}", "}}"
        ), formatted_string_lecture_transcriptions.replace("{", "{{").replace("}", "}}")

    def create_formatted_faq_string(self, faqs, base_url):
        """
        Create a formatted string from the data
        """
        formatted_string = ""
        for faq in faqs:
            faq = (
                f"FAQ ID {faq.get(FaqSchema.FAQ_ID.value)},"
                f" CourseId {faq.get(FaqSchema.COURSE_ID.value)} ,"
                f" FAQ Question title {faq.get(FaqSchema.QUESTION_TITLE.value)} and"
                f" FAQ Question Answer {faq.get(FaqSchema.QUESTION_ANSWER.value)} and"
                f" FAQ link {base_url}/courses/{faq.get(FaqSchema.COURSE_ID.value)}/faq/?faqId="
                f"{faq.get(FaqSchema.FAQ_ID.value)}"
            )
            formatted_string += faq

        return formatted_string.replace("{", "{{").replace("}", "}}")

    def __call__(
        self,
        information,  #: #Union[List[dict], List[str]],
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

        if information_type == InformationType.FAQS:
            paras = self.create_formatted_faq_string(
                information, kwargs.get("base_url")
            )
            self.prompt_str = self.faq_prompt_str
        if information_type == InformationType.PARAGRAPHS:
            paragraphs_page_chunks, paragraphs_transcriptions = (
                self.create_formatted_lecture_string(information)
            )
            self.prompt_str = self.lecture_prompt_str

        try:
            self.default_prompt = PromptTemplate(
                template=self.prompt_str,
                input_variables=["Answer", "Paragraphs"],
            )
            if information_type == InformationType.FAQS:
                response = (self.default_prompt | self.pipeline).invoke(
                    {"Answer": answer, "Paragraphs": paras}
                )
            else:
                response = (self.default_prompt | self.pipeline).invoke(
                    {
                        "Answer": answer,
                        "Paragraphs": paragraphs_page_chunks,
                        "TranscriptionParagraphs": paragraphs_transcriptions,
                    }
                )
            self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
            if response == "!NONE!":
                return answer
            return response
        except Exception as e:
            logger.error("citation pipeline failed %s", e)
            raise e
