import contextvars
import json
import os
import random
from queue import Queue
from threading import Thread
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser

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
            version="gpt-oss:120b" if local else "gpt-5-nano"
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
        preparing_messages = [
            "Looking through the material...",
            "Reviewing relevant topics...",
            "Gathering key concepts...",
            "Identifying important areas to test...",
        ]
        generating_messages = [
            "Writing the question and answer options...",
            "Putting together a good challenge...",
            "Formulating the question...",
            "Creating answer choices...",
        ]

        if callback:
            callback.in_progress(
                "Generating questions...",
                chat_message=random.choice(preparing_messages),  # nosec B311
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
                chat_message=random.choice(generating_messages),  # nosec B311
            )

        response = self.pipeline.invoke([SystemMessage(content=rendered_prompt)])
        self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_MCQ_GENERATION_PIPELINE)

        # Validate JSON
        result = self._extract_and_validate_json(response)
        return result

    def run_in_thread(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]],
        user_language: str,
        callback: Optional[StatusCallback],
        result_storage: dict,
        count: int = 1,
    ) -> Thread:
        """
        Run MCQ generation in a background thread.

        Uses contextvars.copy_context() to preserve the Langfuse observation
        stack across the thread boundary (same pattern as memiris_setup).

        Results are communicated via a Queue stored in result_storage["queue"].
        Each item is a tuple of ("mcq", json_str), ("error", msg), or ("done", None).
        For single-question mode, also stores the result under "mcq_json" for
        backward compatibility.

        :param command: Free-text instruction describing what to generate
        :param chat_history: Recent chat history for context
        :param user_language: "en" or "de"
        :param callback: Status callback for dynamic chat messages
        :param result_storage: Mutable dict for inter-thread communication
        :param count: Number of questions to generate (1 = single, >1 = one-by-one)
        :return: The started Thread handle
        """
        q: Queue = Queue()
        result_storage["queue"] = q
        result_storage["count"] = count
        ctx = contextvars.copy_context()

        def _generate():
            try:
                if count > 1:
                    self._generate_multiple(
                        command, chat_history, user_language, count, q
                    )
                else:
                    result = self(
                        command=command,
                        chat_history=chat_history,
                        user_language=user_language,
                        callback=callback,
                    )
                    result_storage["mcq_json"] = result
                    q.put(("mcq", result))
            except Exception as e:
                logger.error("MCQ generation failed in thread", exc_info=e)
                result_storage["error"] = str(e)
                q.put(("error", str(e)))
            finally:
                q.put(("done", None))

        thread = Thread(
            name="McqGenerationThread",
            target=lambda: ctx.run(_generate),
        )
        thread.start()
        return thread

    def _generate_multiple(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]],
        user_language: str,
        count: int,
        q: Queue,
    ) -> None:
        """Generate multiple MCQ questions one-by-one, pushing each to the queue."""
        previous_questions: list[str] = []

        for i in range(count):
            dedup_context = ""
            if previous_questions:
                dedup_context = (
                    "\n\nQuestions already generated (do NOT repeat these):\n"
                    + "\n".join(f"- {pq}" for pq in previous_questions)
                )
            single_command = (
                f"{command}\n\n"
                f"Generate exactly 1 question (question {i + 1} of {count}). "
                f"Cover a different aspect or subtopic than previous questions."
                f"{dedup_context}"
            )
            try:
                result = self(
                    command=single_command,
                    chat_history=chat_history,
                    user_language=user_language,
                    callback=None,  # avoid thread-safety issues with shared callback
                )
                # Track question text for deduplication
                try:
                    parsed = json.loads(result)
                    if parsed.get("question"):
                        previous_questions.append(parsed["question"])
                except (json.JSONDecodeError, KeyError):
                    pass
                q.put(("mcq", result))
            except Exception as e:
                logger.error(
                    "MCQ generation failed for question %d of %d",
                    i + 1,
                    count,
                    exc_info=e,
                )
                q.put(("error", str(e)))

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
