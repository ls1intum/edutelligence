import logging
from typing import Optional

from langchain_core.prompts import (
    ChatPromptTemplate,
)
from app.common.pyris_message import IrisMessageRole, PyrisMessage
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from app.pipeline.prompts.chat_gpt_wrapper_prompts import chat_gpt_initial_system_prompt

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
        super().__init__(implementation_id="chat_gpt_wrapper_pipeline_reference_impl")
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

        pyris_system_prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[
                TextMessageContentDTO(text_content=chat_gpt_initial_system_prompt)
            ],
        )

        prompts = [pyris_system_prompt] + dto.conversation

        response = self.request_handler.chat(
            prompts, CompletionArguments(temperature=0.4)
        )
        self.callback.done(final_result=response)
