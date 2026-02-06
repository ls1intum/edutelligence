import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.sub_pipeline import SubPipeline
from iris.tracing import observe

logger = get_logger(__name__)


class SessionTitleGenerationPipeline(SubPipeline):
    """
    Pipeline that generates a session title from the conversation history.
    """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    tokens: TokenUsageDTO
    MAX_RECENT_MESSAGES = 10
    MAX_MESSAGE_CHARS = 400

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="session_title_generation_pipeline")

        # Set the langchain chat model
        model = "llama3.3:latest" if local else "gpt-4.1-nano"
        request_handler = ModelVersionRequestHandler(version=model)
        completion_args = CompletionArguments(temperature=0.0, max_tokens=128)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=completion_args,
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
        # Create the pipeline
        self.pipeline = self.llm | StrOutputParser()

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
        user_language: str = "en",
        **kwargs,
    ) -> Optional[str]:
        prompt_text = self.prompt_template.render(user_language=user_language)
        formatted_recent_messages = self.format_recent_messages(recent_messages)
        try:
            logger.info("Running Session Title Generation Pipeline")
            # Keep the rendered text as data so `{}` inside message content is not
            # interpreted as additional prompt template variables.
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", "{prompt_text}"),
                    (
                        "user",
                        "Current title: {current_session_title}\n"
                        "Recent messages (oldest first, newest last):\n"
                        "{recent_messages}\n\n"
                        "Return EXACTLY one line:\n"
                        "KEEP\n"
                        "or\n"
                        "UPDATE: <new title>",
                    ),
                ]
            )
            session_title = (prompt | self.pipeline).invoke(
                {
                    "prompt_text": prompt_text,
                    "current_session_title": current_session_title,
                    "recent_messages": formatted_recent_messages,
                }
            )
            logger.info(
                "Session title raw LLM output | output=%r",
                str(session_title)[:500] if session_title is not None else None,
            )
            self.tokens = self.llm.tokens
            self.tokens.pipeline = PipelineEnum.IRIS_SESSION_TITLE_GENERATION_PIPELINE
            return session_title
        except Exception as e:
            logger.error(
                "An error occurred while running the session title generation pipeline",
                exc_info=e,
            )
            return None
