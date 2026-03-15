import json
import os
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import PyrisMessage
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.sub_pipeline import SubPipeline
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class McqGenerationPipeline(SubPipeline):
    """Subpipeline that generates MCQ questions as JSON using a focused prompt."""

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="mcq_generation_pipeline")
        self.tokens = []

        # Load Jinja2 template
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.prompt_template = jinja_env.get_template("mcq_generation_prompt.j2")

        # Create LLM
        request_handler = ModelVersionRequestHandler(
            version="gpt-oss:120b" if local else "gpt-5-mini"
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=CompletionArguments(temperature=0.7),
        )
        self.pipeline = self.llm | StrOutputParser()

    def __call__(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]] = None,
        user_language: str = "en",
        callback: Optional[StatusCallback] = None,
    ) -> str:
        """
        Generate MCQ questions as a JSON string.

        :param command: Free-text instruction describing what to generate
        :param chat_history: Recent chat history for context
        :param user_language: "en" or "de"
        :param callback: Status callback for dynamic chat messages
        :return: JSON string with MCQ data
        """
        if callback:
            callback.in_progress(
                "Generating questions...",
                chat_message="Reviewing course materials...",
            )

        # Build chat history text for template context
        chat_history_text = self._serialize_chat_history(chat_history)

        # Render the prompt
        rendered_prompt = self.prompt_template.render(
            command=command,
            chat_history_text=chat_history_text,
            user_language=user_language,
        )

        if callback:
            callback.in_progress(
                "Generating questions...",
                chat_message="Crafting questions and explanations...",
            )

        prompt = ChatPromptTemplate.from_messages([("system", rendered_prompt)])
        response = (prompt | self.pipeline).invoke({})
        self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_MCQ_GENERATION_PIPELINE)

        # Validate JSON
        result = self._extract_and_validate_json(response)
        return result

    @staticmethod
    def _serialize_chat_history(
        chat_history: Optional[List[PyrisMessage]],
    ) -> str:
        """Serialize recent chat history into a simple text format."""
        if not chat_history:
            return ""
        lines = []
        for msg in chat_history[-10:]:
            role = msg.sender.value
            for content in msg.contents:
                if hasattr(content, "text_content") and content.text_content:
                    lines.append(f"{role}: {content.text_content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_and_validate_json(response: str) -> str:
        """Extract and validate MCQ JSON from the LLM response."""
        # Strip markdown fences if present
        cleaned = response.strip()
        if cleaned.startswith("```") and "\n" in cleaned:
            first_newline = cleaned.index("\n")
            last_fence = cleaned.rfind("```")
            if last_fence > first_newline:
                start = first_newline + 1
                cleaned = cleaned[start:last_fence].strip()

        parsed = json.loads(cleaned)

        # Validate structure
        mcq_type = parsed.get("type")
        if mcq_type == "mcq":
            _validate_single_mcq(parsed)
        elif mcq_type == "mcq-set":
            questions = parsed.get("questions", [])
            if not questions:
                raise ValueError("mcq-set must contain at least one question")
            for q in questions:
                _validate_single_mcq(q)
        else:
            raise ValueError(f"Unknown MCQ type: {mcq_type}")

        return json.dumps(parsed)


def _validate_single_mcq(mcq: dict) -> None:
    """Validate a single MCQ question structure."""
    if "question" not in mcq:
        raise ValueError("MCQ missing 'question' field")
    options = mcq.get("options", [])
    if len(options) != 4:
        raise ValueError(f"MCQ must have exactly 4 options, got {len(options)}")
    correct_count = sum(1 for opt in options if opt.get("correct"))
    if correct_count != 1:
        raise ValueError(f"MCQ must have exactly 1 correct option, got {correct_count}")
