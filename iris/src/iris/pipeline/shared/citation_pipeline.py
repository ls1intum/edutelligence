import os
from asyncio.log import logger
from enum import Enum
from typing import List, Union

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable

from iris.common.pipeline_enum import PipelineEnum
from iris.llm import CapabilityRequestHandler, CompletionArguments, RequirementList
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.vector_database.faq_schema import FaqSchema
from iris.vector_database.lecture_unit_page_chunk_schema import (
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

    def create_formatted_lecture_string(self, paragraphs):
        """
        Create a formatted string from the data
        """
        formatted_string = ""
        for _, paragraph in enumerate(paragraphs):
            lct = (
                f"Lecture: {paragraph.get(LectureUnitPageChunkSchema.LECTURE_NAME.value)},"
                f" Unit: {paragraph.get(LectureUnitPageChunkSchema.LECTURE_UNIT_NAME.value)},"
                f" Page: {paragraph.get(LectureUnitPageChunkSchema.PAGE_NUMBER.value)},"
                f" Link: {paragraph.get(LectureUnitPageChunkSchema.LECTURE_UNIT_LINK.value) or "No link available"},"
                f"\nContent:\n---{paragraph.get(LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value)}---\n\n"
            )
            formatted_string += lct

        return formatted_string.replace("{", "{{").replace("}", "}}")

    def create_formatted_faq_string(self, faqs, base_url):
        """
        Create a formatted string from the data
        """
        formatted_string = ""
        for _, faq in enumerate(faqs):
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
        information: Union[List[dict], List[str]],
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

        if information_type == InformationType.FAQS:
            paras = self.create_formatted_faq_string(
                information, kwargs.get("base_url")
            )
            self.prompt_str = self.faq_prompt_str
        if information_type == InformationType.PARAGRAPHS:
            paras = self.create_formatted_lecture_string(information)
            self.prompt_str = self.lecture_prompt_str

        try:
            self.default_prompt = PromptTemplate(
                template=self.prompt_str,
                input_variables=["Answer", "Paragraphs"],
            )
            response = (self.default_prompt | self.pipeline).invoke(
                {"Answer": answer, "Paragraphs": paras}
            )
            self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_CITATION_PIPELINE)
            if response == "!NONE!":
                return answer
            return response
        except Exception as e:
            logger.error("citation pipeline failed %s", e)
            raise e
