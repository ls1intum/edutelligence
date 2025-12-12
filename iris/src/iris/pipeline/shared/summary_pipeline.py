import logging
import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import Runnable

from ...llm import ModelVersionRequestHandler
from ...llm.langchain import IrisLangchainCompletionModel
from ..sub_pipeline import SubPipeline

logger = logging.getLogger(__name__)


class SummaryPipeline(SubPipeline):
    """A generic summary pipeline that can be used to summarize any text"""

    llm: IrisLangchainCompletionModel
    pipeline: Runnable
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="summary_pipeline")
        # Set the langchain chat model
        request_handler = ModelVersionRequestHandler(
            version="llama3.3:latest" if local else "gpt-3.5-turbo"
        )
        self.llm = IrisLangchainCompletionModel(
            request_handler=request_handler, max_tokens=1000
        )
        # Load the prompt from a file
        dirname = os.path.dirname(__file__)
        with open(
            os.path.join(dirname, "../prompts/summary_prompt.txt"),
            "r",
            encoding="utf-8",
        ) as file:
            logger.info("Loading summary prompt...")
            self.prompt_str = file.read()
        # Create the prompt
        self.prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(self.prompt_str),
            ]
        )
        # Create the pipeline
        self.pipeline = self.prompt | self.llm | StrOutputParser()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self, query: str, **kwargs) -> str:
        """
        Runs the pipeline
            :param query: The query
            :param kwargs: keyword arguments
            :return: summary text as string
        """
        if query is None:
            raise ValueError("Query must not be None")
        logger.info("Running summary pipeline...")
        response: str = self.pipeline.invoke({"text": query})
        logger.info("Response from summary pipeline: %s...", response[:20])
        return response
