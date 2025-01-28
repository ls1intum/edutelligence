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
from app.llm.langchain.iris_langchain_chat_model import IrisLangchainChatModel
from app.pipeline.prompts.chat_gpt_wrapper_prompts import chat_gpt_initial_system_prompt
from langchain_core.runnables import Runnable

from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.pipeline import Pipeline
from app.web.status.status_update import ChatGPTWrapperStatusCallback

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
    callback: ChatGPTWrapperStatusCallback
    llm: IrisLangchainChatModel
    pipeline: Runnable

    def __init__(self, callback: Optional[ChatGPTWrapperStatusCallback] = None):
        super().__init__(implementation_id="chat_gpt_wrapper_pipeline_reference_impl")
        self.callback = callback
        self.request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
            )
        )

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

        self.callback.in_progress()
        pyris_system_prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[
                TextMessageContentDTO(text_content=chat_gpt_initial_system_prompt)
            ],
        )

        prompts = [pyris_system_prompt] + [
            msg
            for msg in dto.chat_history
            if msg.contents is not None
            and len(msg.contents) > 0
            and msg.contents[0].text_content
            and len(msg.contents[0].text_content) > 0
        ]

        response = self.request_handler.chat(
            prompts, CompletionArguments(temperature=0.5, max_tokens=2000), tools=None
        )

        logger.info(f"ChatGPTWrapperPipeline response: {response}")

        if (
            response.contents is None
            or len(response.contents) == 0
            or response.contents[0].text_content is None
            or len(response.contents[0].text_content) == 0
        ):
            self.callback.error("ChatGPT did not reply. Try resending.")
            # Print lots of debug info for this case
            logger.error(f"ChatGPTWrapperPipeline response: {response}")
            logger.error(f"ChatGPTWrapperPipeline request: {prompts}")
            return

        self.callback.done(final_result=response.contents[0].text_content)
