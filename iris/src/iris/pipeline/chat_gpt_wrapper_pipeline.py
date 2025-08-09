import logging
from typing import List, Optional

from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.runnables import Runnable

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.chat.exercise_chat.exercise_chat_pipeline_execution_dto import (
    ExerciseChatPipelineExecutionDTO,
)
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.variant.chat_gpt_wrapper_variant import ChatGPTWrapperVariant
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.langchain.iris_langchain_chat_model import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.chat_gpt_wrapper_prompts import (
    chat_gpt_initial_system_prompt,
)
from iris.web.status.status_update import ChatGPTWrapperStatusCallback

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


class ChatGPTWrapperPipeline(Pipeline[ChatGPTWrapperVariant]):
    """ChatGPTWrapperPipeline executes a single-step response generation process using ChatGPT.

    It constructs a system prompt along with the chat history, sends the assembled prompts to a model request
    handler, and then invokes the callback with the final response. If no valid response is generated, it logs
    detailed error information.
    """

    callback: ChatGPTWrapperStatusCallback
    llm: IrisLangchainChatModel
    pipeline: Runnable
    tokens: List[str]
    request_handler: ModelVersionRequestHandler

    def __init__(self, callback: Optional[ChatGPTWrapperStatusCallback] = None):
        super().__init__(implementation_id="chat_gpt_wrapper_pipeline_reference_impl")
        self.callback = callback
        self.tokens = []
        self.request_handler = ModelVersionRequestHandler(version="gpt-4.1")

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
            prompts,
            CompletionArguments(temperature=0.5, max_tokens=2000),
            tools=None,
        )

        logger.info("ChatGPTWrapperPipeline response: %s", response)

        if (
            response.contents is None
            or len(response.contents) == 0
            or response.contents[0].text_content is None
            or len(response.contents[0].text_content) == 0
        ):
            self.callback.error("ChatGPT did not reply. Try resending.")
            # Print lots of debug info for this case
            logger.error("ChatGPTWrapperPipeline response: %s", response)
            logger.error("ChatGPTWrapperPipeline request: %s", prompts)
            return

        self.callback.done(final_result=response.contents[0].text_content)

    @classmethod
    def get_variants(cls) -> List[ChatGPTWrapperVariant]:
        """
        Returns available variants for the ChatGPTWrapperPipeline.

        Returns:
            List of ChatGPTWrapperVariant objects representing available variants
        """
        return [
            ChatGPTWrapperVariant(
                variant_id="chat-gpt-wrapper",
                name="ChatGPT Wrapper",
                description="Uses ChatGPT model to respond to queries.",
                agent_model="gpt-4.1",
            )
        ]
