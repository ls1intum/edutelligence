from operator import itemgetter

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from domain import IrisMessage, IrisMessageRole
from domain.dtos import BaseChatModel
from llm.langchain import IrisLangchainChatModel
from pipeline import Pipeline


class SimpleChatPipeline(Pipeline):
    """A simple chat pipeline that uses our custom langchain chat model for our own request handler"""

    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __init__(self, llm: IrisLangchainChatModel):
        self.llm = llm
        self.pipeline = {"query": itemgetter("query")} | llm | StrOutputParser()
        super().__init__(implementation_id="simple_chat_pipeline")

    def __call__(self, dto: BaseChatModel, **kwargs) -> IrisMessage:
        """
        Gets a response from the langchain chat model
        """
        query = dto.query
        if query is None:
            raise ValueError("IrisMessage must not be None")
        message = query.text
        response = self.pipeline.invoke({"question": message})
        return IrisMessage(role=IrisMessageRole.ASSISTANT, text=response)
