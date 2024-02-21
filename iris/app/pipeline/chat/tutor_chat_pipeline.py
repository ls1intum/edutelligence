import logging
import os

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.runnables import Runnable

from domain import IrisMessage, IrisMessageRole
from llm.langchain import IrisLangchainChatModel

from pipeline import Pipeline

logger = logging.getLogger(__name__)


class TutorChatPipeline(Pipeline):
    """Tutor chat pipeline that answers exercises related questions from students."""

    _is_abstract: bool = False
    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(self, llm: IrisLangchainChatModel):
        super().__init__(implementation_id="tutor_chat_pipeline_reference_impl")
        # Set the langchain chat model
        self.llm = llm
        # Load the prompt from a file
        dirname = os.path.dirname(__file__)
        with open(
            os.path.join(dirname, "../prompts/iris_tutor_chat_prompt.txt", "r")
        ) as file:
            logger.debug("Loading tutor chat prompt...")
            prompt_str = file.read()
        # Create the prompt
        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(prompt_str),
            ]
        )
        # Create the pipeline
        self.pipeline = prompt | llm | StrOutputParser()

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self, query: IrisMessage, **kwargs) -> IrisMessage:
        """
        Runs the pipeline
            :param query: The query
            :return: IrisMessage
        """
        if query is None:
            raise ValueError("IrisMessage must not be None")
        message = query.text
        logger.debug("Running tutor chat pipeline...")
        response = self.pipeline.invoke({"question": message})
        logger.debug(f"Response from tutor chat pipeline: {response}")
        return IrisMessage(role=IrisMessageRole.ASSISTANT, text=response)
