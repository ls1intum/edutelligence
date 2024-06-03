import os
from asyncio.log import logger
from typing import Optional, List, Union

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable

from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline

from app.vector_database.lecture_schema import LectureSchema


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
                gpt_version_equivalent=3.5,
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
            self.prompt_str = file.read()
        self.pipeline = self.llm | StrOutputParser()

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def create_formatted_string(self, paragraphs):
        """
        Create a formatted string from the data
        """
        formatted_string = ""
        for i, paragraph in enumerate(paragraphs):
            para = paragraph.get(LectureSchema.PAGE_TEXT_CONTENT.value, "")
            title = (
                "Lecture Title:"
                + paragraph.get(LectureSchema.COURSE_NAME.value, "")
                + paragraph.get(LectureSchema.LECTURE_NAME.value, "")
            )
            page_number = paragraph.get(LectureSchema.PAGE_NUMBER.value, "")
            formatted_string += (
                "-" * 50 + "\n\n"
                f"{title}page {page_number}:"
                f"\n\n{para}\n" + "-" * 50 + "\n\n"
            )

        return (
            formatted_string.replace("{", "{{").replace("}", "}}")
            + "\n Answer with citations: \n"
        )

    def __call__(
        self,
        paragraphs: Union[List[dict], List[str]],
        answer: str,
        prompt: Optional[PromptTemplate] = None,
        **kwargs,
    ) -> List[str]:
        """
        Runs the pipeline
            :param paragraphs: List of paragraphs which can be list of dicts or list of strings
            :param query: The query
            :return: Selected file content
        """
        self.prompt_str += "\n" + self.create_formatted_string(paragraphs)

        try:
            self.default_prompt = PromptTemplate(
                template=self.prompt_str,
                input_variables=["Answer"],
            )
            response = (self.default_prompt | self.pipeline).invoke({"Answer": answer})
            return response
        except Exception as e:
            logger.error("citation pipeline failed", e)
            raise e
