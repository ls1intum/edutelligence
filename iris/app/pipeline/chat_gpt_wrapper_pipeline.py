import logging
from typing import Optional

from langchain_core.prompts import (
    ChatPromptTemplate,
)

from app.domain.chat_gpt_wrapper_pipeline_execution_dto import (
    ChatGPTWrapperPipelineExecutionDTO,
)
from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.pipeline import Pipeline
from app.web.status.status_update import ChatGPTWrapperCallback

logger = logging.getLogger(__name__)


class ChatGPTWrapperPipeline(Pipeline):
    callback: ChatGPTWrapperCallback
    request_handler: CapabilityRequestHandler

    def __init__(self, callback: Optional[ChatGPTWrapperCallback] = None):
        super().__init__(
            implementation_id="chat_gpt_wrapper_pipeline_reference_impl"
        )
        self.callback = callback
        self.request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
            )
        )
        self.tokens = []

    def __call__(
        self,
        dto: ChatGPTWrapperPipelineExecutionDTO,
        prompt: Optional[ChatPromptTemplate] = None,
        **kwargs,
    ):
        """
        Run the ChatGPT wrapper pipeline.
        This consists of a single response generation step.
        """
        if not dto.conversation:
            raise ValueError("Conversation with at least one message is required")

        response = self.request_handler.chat(
            dto.conversation, CompletionArguments(temperature=0.4)
        )
        self.callback.done(final_result=response)