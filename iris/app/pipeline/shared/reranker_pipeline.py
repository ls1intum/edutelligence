import os
from asyncio.log import logger
from typing import Optional, List

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable

from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.pipeline.chat.output_models.output_models.selected_paragraphs import (
    SelectedParagraphs,
)
from app.vector_database.lecture_schema import LectureSchema


class RerankerPipeline(Pipeline):
    """A generic reranker pipeline that can be used to rerank a list of documents based on a question"""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self):
        super().__init__(implementation_id="reranker_pipeline")
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=3.5,
                context_length=4096,
            )
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=CompletionArguments(temperature=0, max_tokens=4000),
        )
        dirname = os.path.dirname(__file__)
        prompt_file_path = os.path.join(dirname, "..", "prompts", "reranker_prompt.txt")
        with open(prompt_file_path, "r") as file:
            logger.info("Loading reranker prompt...")
            prompt_str = file.read()

        self.output_parser = PydanticOutputParser(pydantic_object=SelectedParagraphs)
        self.default_prompt = PromptTemplate(
            template=prompt_str,
            input_variables=["file_names", "feedbacks"],
            partial_variables={
                "format_instructions": self.output_parser.get_format_instructions()
            },
        )
        logger.debug(self.output_parser.get_format_instructions())
        self.pipeline = self.llm | self.output_parser

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(
        self,
        paragraphs: list[dict],
        query: str,
        prompt: Optional[ChatPromptTemplate] = None,
        **kwargs,
    ) -> List[str]:
        """
        Runs the pipeline
            :param query: The query
            :return: Selected file content
        """
        data = {
            f"paragraph_{i}": paragraphs[i].get(LectureSchema.PAGE_TEXT_CONTENT.value)
            + "\n"
            + paragraphs[i].get(LectureSchema.PAGE_IMAGE_DESCRIPTION.value)
            for i in range(len(paragraphs))
        }
        data["question"] = query
        if prompt is None:
            prompt = self.default_prompt
        response = (prompt | self.pipeline).invoke(data)
        return response.selected_paragraphs
