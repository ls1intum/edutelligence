from typing import List

from langchain_core.messages import AIMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.runnables import Runnable
from pydantic.v1 import BaseModel, Field

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from iris.tracing import observe

from ...common.message_converters import (
    convert_iris_message_to_langchain_message,
)
from ...common.pyris_message import PyrisMessage
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ...llm.langchain import IrisLangchainChatModel
from ..prompts.iris_interaction_suggestion_prompts import (
    course_chat_begin_prompt,
    course_chat_history_exists_prompt,
    default_chat_begin_prompt,
    default_chat_history_exists_prompt,
    exercise_chat_begin_prompt,
    exercise_chat_history_exists_prompt,
    iris_course_suggestion_initial_system_prompt,
    iris_default_suggestion_initial_system_prompt,
    iris_exercise_suggestion_initial_system_prompt,
)
from ..sub_pipeline import SubPipeline

logger = get_logger(__name__)


class Questions(BaseModel):
    questions: List[str] = Field(description="questions that students may ask")


class InteractionSuggestionPipeline(SubPipeline):
    """
    Interaction suggestion pipeline that suggests next chat interactions, either for exercises or courses.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    prompt: ChatPromptTemplate
    variant: str
    tokens: TokenUsageDTO

    def __init__(self, variant: str = "default"):
        super().__init__(implementation_id="interaction_suggestion_pipeline")

        self.variant = variant

        # Set the langchain chat model
        model = "gpt-4.1-nano"  # Default model for all variants

        request_handler = ModelVersionRequestHandler(version=model)
        completion_args = CompletionArguments(
            temperature=0.6, max_tokens=2000, response_format="JSON"
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

    @observe(name="Interaction Suggestion Pipeline")
    def __call__(
        self,
        dto: InteractionSuggestionPipelineExecutionDTO,
        user_language: str = "en",
        **kwargs,
    ) -> list[str]:
        """
        Runs the pipeline
            :param dto: The pipeline execution data transfer object
            :param user_language: The user's preferred language ("en" or "de")
            :param kwargs: The keyword arguments

        """
        iris_suggestion_initial_system_prompt = (
            iris_default_suggestion_initial_system_prompt
        )
        chat_history_exists_prompt = default_chat_history_exists_prompt
        chat_begin_prompt = default_chat_begin_prompt

        if self.variant == "course":
            iris_suggestion_initial_system_prompt = (
                iris_course_suggestion_initial_system_prompt
            )
            chat_history_exists_prompt = course_chat_history_exists_prompt
            chat_begin_prompt = course_chat_begin_prompt
        elif self.variant == "exercise":
            iris_suggestion_initial_system_prompt = (
                iris_exercise_suggestion_initial_system_prompt
            )
            chat_history_exists_prompt = exercise_chat_history_exists_prompt
            chat_begin_prompt = exercise_chat_begin_prompt

        # Add language instruction
        if user_language == "de":
            language_instruction = "\nGenerate questions in German, using 'du' form."
        else:
            language_instruction = "\nGenerate questions in English."

        try:
            logger.info("Running course interaction suggestion pipeline...")

            history: List[PyrisMessage] = dto.chat_history or []

            # Add the conversation to the prompt
            chat_history_messages = [
                convert_iris_message_to_langchain_message(message)
                for message in history[-4:]
            ]
            if dto.last_message:
                last_message = AIMessage(
                    content=dto.last_message.replace("{", "{{").replace("}", "}}"),
                )
                chat_history_messages.append(last_message)
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        (
                            "system",
                            iris_suggestion_initial_system_prompt
                            + "\n"
                            + chat_history_exists_prompt
                            + language_instruction,
                        ),
                        *chat_history_messages,
                        ("system", chat_begin_prompt),
                    ]
                )

                prob_st_val = dto.problem_statement or "No problem statement provided."
                prompt_val = self.prompt.format_messages(problem_statement=prob_st_val)
                self.prompt = ChatPromptTemplate.from_messages(prompt_val)

                response: dict = (self.prompt | self.pipeline).invoke({})
                self.tokens = self.llm.tokens
                self.tokens.pipeline = PipelineEnum.IRIS_INTERACTION_SUGGESTION
                return response["questions"]
            else:
                raise ValueError("No last message provided")
        except Exception as e:
            logger.error(
                "An error occurred while running the interaction suggestion chat pipeline",
                exc_info=e,
            )
            return []
