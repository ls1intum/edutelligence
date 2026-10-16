import os
from typing import List

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from iris.tracing import observe

from ...common.message_converters import normalize_history_message
from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from ...llm.iris_chat_model import IrisChatModel
from ...llm.llm_configuration import resolve_model
from ..sub_pipeline import SubPipeline

logger = get_logger(__name__)

_HISTORY_MESSAGES = 4


class Questions(BaseModel):
    """Follow-up questions the student may click."""

    questions: List[str] = Field(description="questions that students may ask")


def _text(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


class InteractionSuggestionPipeline(SubPipeline):
    """
    Interaction suggestion pipeline that suggests next chat interactions, either for exercises or courses.
    """

    llm: IrisChatModel
    variant: str
    tokens: TokenUsageDTO | None
    local: bool

    def __init__(self, variant: str = "default", local: bool = False):
        super().__init__(implementation_id="interaction_suggestion_pipeline")

        self.variant = variant
        self.local = local
        self.tokens = None

        pipeline_id = "interaction_suggestion_pipeline"
        model = resolve_model(pipeline_id, variant, "chat", local=local)
        self.llm = IrisChatModel(
            LlmRequestHandler(model_id=model),
            CompletionArguments(temperature=0.3 if local else 0.6),
        )
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.prompt_template = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        ).get_template("interaction_suggestion_prompt.j2")

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm}, local={self.local})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm}, local={self.local})"

    @observe(name="Interaction Suggestion Pipeline")
    def __call__(
        self,
        dto: InteractionSuggestionPipelineExecutionDTO,
        language: str = "English",
        **kwargs,
    ) -> list[str]:
        """
        Runs the pipeline
            :param dto: The pipeline execution data transfer object
            :param language: Name of the language of the answer, such as "German"
            :param kwargs: The keyword arguments

        """
        try:
            logger.info(
                "Running interaction suggestion pipeline (local=%s)...",
                self.local,
            )
            if not dto.last_message:
                raise ValueError("No last message provided")

            history: List[PyrisMessage] = dto.chat_history or []
            messages = [
                _text(
                    IrisMessageRole.SYSTEM,
                    self.prompt_template.render(
                        variant=self.variant,
                        language=language,
                        problem_statement=dto.problem_statement
                        or "No problem statement provided.",
                    ),
                )
            ]
            messages.extend(
                normalize_history_message(message)
                for message in history[-_HISTORY_MESSAGES:]
            )
            messages.append(_text(IrisMessageRole.ASSISTANT, dto.last_message))
            messages.append(
                _text(
                    IrisMessageRole.USER,
                    "Suggest the two follow-up questions for the conversation above.",
                )
            )

            response = self.llm.structured(messages, Questions)
            self.tokens = self.llm.tokens
            if self.tokens is not None:
                self.tokens.pipeline = PipelineEnum.IRIS_INTERACTION_SUGGESTION
            return [
                question.strip() for question in response.questions if question.strip()
            ][:2]

        except Exception as e:
            logger.error(
                "An error occurred while running the interaction suggestion pipeline (local=%s)",
                self.local,
                exc_info=e,
            )
            if self.llm.tokens is not None:
                self.tokens = self.llm.tokens
                self.tokens.pipeline = PipelineEnum.IRIS_INTERACTION_SUGGESTION
            return []
