import logging
import os
from typing import Dict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.runnables import Runnable

from ...llm import BasicRequestHandler
from ...llm.langchain import IrisLangchainCompletionModel
from ...pipeline import Pipeline

logger = logging.getLogger(__name__)


class SummaryPipeline(Pipeline):
    """A generic summary pipeline that can be used to summarize any text"""

    _cache: Dict = {}
    llm: IrisLangchainCompletionModel
    pipeline: Runnable
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self):
        super().__init__(implementation_id="summary_pipeline")
        # Set the langchain chat model
        request_handler = BasicRequestHandler("gpt35-completion")
        self.llm = IrisLangchainCompletionModel(
            request_handler=request_handler, max_tokens=1000
        )
        # Load the prompt from a file
        dirname = os.path.dirname(__file__)
        with open(os.path.join(dirname, "../prompts/summary_prompt.txt"), "r") as file:
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
        if _cache := self._cache.get(query):
            logger.info(f"Returning cached summary for query: {query[:20]}...")
            return _cache
        response: str = self.pipeline.invoke({"text": query})
        logger.info(f"Response from summary pipeline: {response[:20]}...")
        self._cache[query] = response
        return response
