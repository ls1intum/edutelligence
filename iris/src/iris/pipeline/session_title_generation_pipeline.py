import os
from typing import Literal, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.iris_chat_model import IrisChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe

logger = get_logger(__name__)


class TitleDecision(BaseModel):
    """Whether to keep the chat title, and the new title when it changes."""

    decision: Literal["keep", "update"]
    title: Optional[str] = Field(
        description="The new title (2-5 words) when decision is update, else null"
    )


def _message(sender: IrisMessageRole, text: str) -> PyrisMessage:
    return PyrisMessage(
        sender=sender, contents=[TextMessageContentDTO(textContent=text)]
    )


class SessionTitleGenerationPipeline(SubPipeline):
    """
    Pipeline that generates a session title from the conversation history.
    """

    llm: IrisChatModel
    tokens: TokenUsageDTO
    MAX_RECENT_MESSAGES = 10
    MAX_MESSAGE_CHARS = 400

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="session_title_generation_pipeline")
        self.tokens = None

        pipeline_id = "session_title_generation_pipeline"
        model = resolve_model(pipeline_id, "default", "chat", local=local)
        self.llm = IrisChatModel(
            LlmRequestHandler(model_id=model),
            CompletionArguments(temperature=0.0, max_tokens=60),
        )
        # Set up Jinja2 environment and load the prompt template
        template_dir = os.path.join(os.path.dirname(__file__), "prompts", "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.prompt_template = self.jinja_env.get_template(
            "session_title_generation_prompt.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @classmethod
    def format_recent_messages(cls, recent_messages: list[str]) -> str:
        max_recent_messages = cls.MAX_RECENT_MESSAGES
        selected_messages = recent_messages[-max_recent_messages:]
        if not selected_messages:
            return "(no recent messages)"

        formatted_lines: list[str] = []
        for idx, msg in enumerate(selected_messages, start=1):
            normalized = str(msg or "").replace("\n", " ").strip()
            if len(normalized) > cls.MAX_MESSAGE_CHARS:
                normalized = normalized[: cls.MAX_MESSAGE_CHARS - 3].rstrip() + "..."
            formatted_lines.append(f"{idx}. {normalized}")
        return "\n".join(formatted_lines)

    @observe(name="Session Title Generation Pipeline")
    def __call__(
        self,
        current_session_title: str,
        recent_messages: list[str],
        language: str = "English",
        **kwargs,
    ) -> Optional[str]:
        """Return "KEEP" or "UPDATE: <title>" (the protocol callers expect)."""
        prompt_text = self.prompt_template.render(language=language)
        formatted_recent_messages = self.format_recent_messages(recent_messages)
        try:
            logger.info("Running Session Title Generation Pipeline")
            decision = self.llm.structured(
                [
                    _message(IrisMessageRole.SYSTEM, prompt_text),
                    _message(
                        IrisMessageRole.USER,
                        f"Current title: {current_session_title}\n"
                        "Recent messages (oldest first, newest last):\n"
                        f"{formatted_recent_messages}",
                    ),
                ],
                TitleDecision,
            )
            logger.info("Session title decision | %s", decision.model_dump())
            self.tokens = self.llm.tokens
            self.tokens.pipeline = PipelineEnum.IRIS_SESSION_TITLE_GENERATION_PIPELINE
            title = (decision.title or "").strip()
            if decision.decision == "update" and title:
                return f"UPDATE: {title}"
            return "KEEP"
        except Exception as e:
            logger.error(
                "An error occurred while running the session title generation pipeline",
                exc_info=e,
            )
            if self.llm.tokens is not None:
                self.tokens = self.llm.tokens
                self.tokens.pipeline = (
                    PipelineEnum.IRIS_SESSION_TITLE_GENERATION_PIPELINE
                )
            return None
