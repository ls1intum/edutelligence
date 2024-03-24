import logging
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.runnables import Runnable
from ...domain import TutorChatPipelineExecutionDTO
from ...web.status.status_update import TutorChatStatusCallback
from ...llm.langchain import IrisLangchainChatModel
from ..pipeline import Pipeline
from weaviate import WeaviateClient

logger = logging.getLogger(__name__)


class LectureChatPipeline(Pipeline):
    """Exercise chat pipeline that answers exercises related questions from students."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorChatStatusCallback
    prompt: ChatPromptTemplate
    db: WeaviateClient

    def __init__(self, callback: TutorChatStatusCallback, pipeline: Runnable, llm: IrisLangchainChatModel):
        super().__init__(implementation_id="lecture_chat_pipeline")
        self.llm = llm
        self.callback = callback
        self.pipeline = pipeline

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self, dto: TutorChatPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline
            :param kwargs: The keyword arguments
        """
        pass
