import logging
import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.runnables import Runnable

from domain import IrisMessage, IrisMessageRole
from llm.langchain import IrisLangchainChatModel
from pipeline import AbstractPipeline


logger = logging.getLogger(__name__)


class TutorChatPipeline(AbstractPipeline):
    """Tutor chat pipeline that answers exercises related questions from students."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt_str: str
    prompt: ChatPromptTemplate

    def __init__(self, llm: IrisLangchainChatModel, name=None):
        super().__init__(name=name)
        # Set the langchain chat model
        self.llm = llm
        # Load the prompt from a file
        dirname = os.path.dirname(__file__)
        with open(
            os.path.join(dirname, "../prompts/iris_tutor_chat_prompt.txt", "r")
        ) as file:
            logger.debug("Loading tutor chat prompt...")
            self.prompt_str = file.read()
        # Create the prompt
        self.prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(self.prompt_str),
            ]
        )
        # Create the pipeline
        self.pipeline = self.prompt | llm | StrOutputParser()

    def __call__(self, query: IrisMessage, **kwargs) -> IrisMessage:
        """
        Runs the pipeline
            :param query: The query
            :param kwargs: keyword arguments
            :return: IrisMessage
        """
        if query is None:
            raise ValueError("IrisMessage must not be None")
        message = query.text
        logger.debug("Running tutor chat pipeline...")
        response = self.pipeline.invoke({"question": message})
        logger.debug(f"Response from tutor chat pipeline: {response}")
        return IrisMessage(role=IrisMessageRole.ASSISTANT, text=response)
