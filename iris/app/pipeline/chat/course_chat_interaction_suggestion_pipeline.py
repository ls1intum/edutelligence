import logging
import traceback
from datetime import datetime
from typing import List, Optional

from langchain_core.messages import AIMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.runnables import Runnable
from pydantic.v1 import Field, BaseModel

from ...common import convert_iris_message_to_langchain_message
from ...domain import PyrisMessage
from ...domain.chat.course_chat.course_chat_interaction_suggestion_dto import (
    CourseChatInteractionSuggestionPipelineExecutionDTO,
)
from ...llm import CapabilityRequestHandler, RequirementList
from ..prompts.iris_interaction_suggestion_prompts import (
    begin_prompt,
    iris_initial_system_prompt,
    chat_history_exists_prompt,
    no_chat_history_prompt,
)

from ...llm import CompletionArguments
from ...llm.langchain import IrisLangchainChatModel

from ..pipeline import Pipeline

logger = logging.getLogger(__name__)


class Questions(BaseModel):
    questions: List[str] = Field(description="questions that students may ask")


class CourseInteractionSuggestionPipeline(Pipeline):
    """Course chat pipeline that answers course related questions from students."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate
    variant: str

    def __init__(self, variant: str = "default"):
        super().__init__(implementation_id="course_interaction_suggestion_pipeline")

        self.variant = variant

        # Set the langchain chat model
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
                json_mode=True,
            )
        )
        completion_args = CompletionArguments(
            temperature=0.2, max_tokens=2000, response_format="JSON"
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )

        # Create the pipeline
        self.pipeline = self.llm | JsonOutputParser(pydantic_object=Questions)

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(
        self, dto: CourseChatInteractionSuggestionPipelineExecutionDTO, **kwargs
    ) -> list[str]:
        """
        Runs the pipeline
            :param dto: The pipeline execution data transfer object
            :param kwargs: The keyword arguments

        """

        try:
            logger.info("Running course interaction suggestion pipeline...")
            last

            history: List[PyrisMessage] = dto.chat_history or []
            query: Optional[PyrisMessage] = (
                dto.chat_history[-1] if dto.chat_history else None
            )

            if query is not None:
                # Add the conversation to the prompt
                chat_history_messages = [
                    convert_iris_message_to_langchain_message(message)
                    for message in history
                ]
                if dto.last_message:
                    logger.info(f"Last message: {dto.last_message}")
                    last_message = AIMessage(content=dto.last_message)
                    chat_history_messages.append(last_message)

                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        (
                            "system",
                            iris_initial_system_prompt
                            + "\n"
                            + chat_history_exists_prompt,
                        ),
                        *chat_history_messages,
                        ("system", begin_prompt),
                    ]
                )
            else:
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        (
                            "system",
                            iris_initial_system_prompt
                            + "\n"
                            + no_chat_history_prompt
                            + "\n"
                            + begin_prompt,
                        ),
                    ]
                )
                response: Questions = (self.prompt | self.pipeline).invoke({})
                return response.questions
        except Exception as e:
            logger.error(
                f"An error occurred while running the course chat pipeline", exc_info=e
            )
            traceback.print_exc()
            return []


def datetime_to_string(dt: Optional[datetime]) -> str:
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
