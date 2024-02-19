import logging
import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.runnables import Runnable

from llm.langchain import IrisLangchainChatModel
from pipeline import Pipeline

logger = logging.getLogger(__name__)


class SummaryPipeline(Pipeline):
    """A generic summary pipeline that can be used to summarize any text"""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self, llm: IrisLangchainChatModel):
        super().__init__(implementation_id="summary_pipeline")
        # Set the langchain chat model
        self.llm = llm
        # Load the prompt from a file
        dirname = os.path.dirname(__file__)
        with open(os.path.join(dirname, "../prompts/summary_prompt.txt"), "r") as file:
            logger.debug("Loading summary prompt...")
            self.prompt_str = file.read()
        # Create the prompt
        self.prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(self.prompt_str),
            ]
        )
        # Create the pipeline
        self.pipeline = self.prompt | llm | StrOutputParser()

    def __call__(self, query: str, **kwargs) -> str:
        """
        Runs the pipeline
            :param query: The query
            :param kwargs: keyword arguments
            :return: summary text as string
        """
        if query is None:
            raise ValueError("Query must not be None")
        logger.debug("Running summary pipeline...")
        response = self.pipeline.invoke({"text": query})
        logger.debug(f"Response from summary pipeline: {response}")
        return response
