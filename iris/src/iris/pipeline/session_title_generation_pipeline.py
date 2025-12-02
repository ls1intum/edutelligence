import logging
import traceback
from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.prompts.session_title_generation_prompt import (
    session_title_generation_prompt,
)
from iris.pipeline.sub_pipeline import SubPipeline

logger = logging.getLogger(__name__)


class SessionTitleGenerationPipeline(SubPipeline):
    """
    Pipeline that generates a session title from the first user message and the LLM response for all iris chats.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    tokens: TokenUsageDTO

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="session_title_generation_pipeline")

        # Set the langchain chat model
        model = "gemma3:4b" if local else "gpt-4.1-nano"
        request_handler = ModelVersionRequestHandler(version=model)
        completion_args = CompletionArguments(temperature=0.2, max_tokens=30)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=completion_args,
        )
        # Create the pipeline
        self.pipeline = self.llm | StrOutputParser()

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Session Title Generation Pipeline")
    def __call__(
        self, first_user_msg: str, llm_response: str, **kwargs
    ) -> Optional[str]:
        prompt = ChatPromptTemplate.from_messages(
            [("system", session_title_generation_prompt())]
        )
        try:
            logger.info("Running Session Title Generation Pipeline")
            session_title = (prompt | self.pipeline).invoke(
                {"first_user_msg": first_user_msg, "llm_response": llm_response}
            )
            self.tokens = self.llm.tokens
            self.tokens.pipeline = PipelineEnum.IRIS_SESSION_TITLE_GENERATION_PIPELINE
            return session_title
        except Exception as e:
            logger.error(
                "An error occurred while running the session title generation pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            return None
