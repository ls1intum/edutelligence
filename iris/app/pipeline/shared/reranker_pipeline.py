import os
from asyncio.log import logger
from typing import Optional, List, Union

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from app.common.pyris_message import PyrisMessage
from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.common.PipelineEnum import PipelineEnum
from app.llm.langchain import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.pipeline.chat.output_models.output_models.selected_paragraphs import (
    SelectedParagraphs,
)
from app.vector_database.lecture_slide_schema import LectureUnitPageChunkSchema


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
                context_length=16385,
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
            input_variables=[
                "question",
                "paragraphs" "chat_history",
            ],
            partial_variables={
                "format_instructions": self.output_parser.get_format_instructions()
            },
        )
        logger.debug(self.output_parser.get_format_instructions())
        self.pipeline = self.llm | self.output_parser
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Lecture Retrieval: Paragraph Selection")
    def __call__(
        self,
        paragraphs: Union[List[dict], List[str]],
        query: str,
        prompt: Optional[PromptTemplate] = None,
        chat_history: list[PyrisMessage] = None,
        **kwargs,
    ) -> List[str]:
        """
        Runs the pipeline
            :param paragraphs: List of paragraphs which can be list of dicts or list of strings
            :param query: The query
            :return: Selected file content
        """
        # Determine if paragraphs are a list of dicts or strings and prepare data accordingly
        paras = ""
        if paragraphs and isinstance(paragraphs[0], dict):
            for i, paragraph in enumerate(paragraphs):
                paras += "Paragraph {}:\n{}\n".format(
                    str(i), paragraph.get(LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value, "")
                )
        elif paragraphs and isinstance(paragraphs[0], str):
            for i, paragraph in enumerate(paragraphs):
                paras += "Paragraph {}:\n{}\n".format(str(i), paragraph)
        else:
            raise ValueError(
                "Invalid input type for paragraphs. Must be a list of dictionaries or a list of strings."
            )

        text_chat_history = [
            chat_history[-i - 1].contents[0].text_content
            for i in range(min(4, len(chat_history)))  # Ensure no out-of-bounds error
        ][
            ::-1
        ]  # Reverse to get the messages in chronological order of their appearance  data["question"] = query
        data = {
            "chat_history": text_chat_history,
            "question": query,
            "paragraphs": paras,
        }
        if prompt is None:
            prompt = self.default_prompt

        response = (prompt | self.pipeline).invoke(data)
        self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_RERANKER_PIPELINE)
        return response.selected_paragraphs
