import logging
from typing import List, Optional

from langchain_core.prompts import (
    ChatPromptTemplate,
)
from app.common.pyris_message import IrisMessageRole, PyrisMessage
from app.domain.chat.exercise_chat.exercise_chat_pipeline_execution_dto import (
    ExerciseChatPipelineExecutionDTO,
)
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from app.pipeline.prompts.chat_gpt_wrapper_prompts import chat_gpt_initial_system_prompt
from langchain_core.messages import SystemMessage, HumanMessage

from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.pipeline import Pipeline
from app.web.status.status_update import ExerciseChatStatusCallback

logger = logging.getLogger(__name__)


def convert_chat_history_to_str(chat_history: List[PyrisMessage]) -> str:
    """
    Converts the chat history to a string
    :param chat_history: The chat history
    :return: The chat history as a string
    """

    def map_message_role(role: IrisMessageRole) -> str:
        if role == IrisMessageRole.SYSTEM:
            return "System"
        elif role == IrisMessageRole.ASSISTANT:
            return "AI Tutor"
        elif role == IrisMessageRole.USER:
            return "Student"
        else:
            return "Unknown"

    return "\n\n".join(
        [
            f"{map_message_role(message.sender)} {"" if not message.sent_at else f"at {message.sent_at.strftime(
                "%Y-%m-%d %H:%M:%S")}"}: {message.contents[0].text_content}"
            for message in chat_history
        ]
    )


class ChatGPTWrapperPipeline(Pipeline):
    callback: ExerciseChatStatusCallback
    request_handler: CapabilityRequestHandler

    def __init__(self, callback: Optional[ExerciseChatStatusCallback] = None):
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
        dto: ExerciseChatPipelineExecutionDTO,
        prompt: Optional[ChatPromptTemplate] = None,
        **kwargs,
    ):
        """
        Run the ChatGPT wrapper pipeline.
        This consists of a single response generation step.
        """
        query = dto.chat_history[-1] if dto.chat_history else None
        if query and query.sender != IrisMessageRole.USER:
            query = None

        chat_history = (
            dto.chat_history[-5:] if query is None else dto.chat_history[-6:-1]
        )

        chat_history_messages = convert_chat_history_to_str(chat_history)

        prompts = ChatPromptTemplate.from_messages(
            [
                SystemMessage(chat_gpt_initial_system_prompt),
                HumanMessage(chat_history_messages),
            ]
        )

        response = self.request_handler.chat(
            prompts, CompletionArguments(temperature=0.4)
        )
        self.callback.done(final_result=response)
