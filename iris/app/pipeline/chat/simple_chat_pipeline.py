from operator import itemgetter

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from domain import IrisMessage, IrisMessageRole
from llm.langchain import IrisLangchainChatModel
from pipeline import AbstractPipeline


class SimpleChatPipeline(AbstractPipeline):
    """A simple chat pipeline that uses our custom langchain chat model for our own request handler"""

    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(self, llm: IrisLangchainChatModel, name=None):
        self.llm = llm
        self.pipeline = {"query": itemgetter("query")} | llm | StrOutputParser()
        super().__init__(name=name)

    def __call__(self, query: IrisMessage, **kwargs) -> IrisMessage:
        """
        Runs the pipeline and is intended to be called by __call__
        :param query: The query
        :param kwargs: keyword arguments
        :return: IrisMessage
        """
        if query is None:
            raise ValueError("IrisMessage must not be None")
        message = query.text
        response = self.pipeline.invoke({"query": message})
        return IrisMessage(role=IrisMessageRole.ASSISTANT, text=response)
