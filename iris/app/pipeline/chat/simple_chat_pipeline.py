from operator import itemgetter

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from domain import IrisMessage, IrisMessageRole
from llm.langchain import IrisLangchainChatModel
from pipeline.chat.chat_pipeline import ChatPipeline


class SimpleChatPipeline(ChatPipeline):
    """A simple chat pipeline that uses our custom langchain chat model for our own request handler"""

    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(self, llm: IrisLangchainChatModel):
        self.llm = llm
        self.pipeline = {"query": itemgetter("query")} | llm | StrOutputParser()
        super().__init__(implementation_id="simple_chat_pipeline")

    def __call__(self, query: IrisMessage, **kwargs) -> IrisMessage:
        """
        Gets a response from the langchain chat model
        """
        if query is None:
            raise ValueError("IrisMessage must not be None")
        message = query.text
        response = self.pipeline.invoke({"query": message})
        return IrisMessage(role=IrisMessageRole.ASSISTANT, text=response)
