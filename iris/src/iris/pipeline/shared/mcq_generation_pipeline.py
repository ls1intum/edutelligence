import contextvars
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from typing import List, Optional

from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import PyrisMessage
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.prompts.environment import prompt_environment
from iris.pipeline.sub_pipeline import SubPipeline
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class McqGenerationPipeline(SubPipeline):
    """Subpipeline that generates MCQ questions as JSON using a focused prompt."""

    def __init__(self, local: bool = False):
        super().__init__(implementation_id="mcq_generation_pipeline")
        self.tokens = []
        self.local = local

        # Load Jinja2 template
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        jinja_env = prompt_environment(template_dir)
        self.prompt_template = jinja_env.get_template("mcq_generation_prompt.j2")

        # Create LLM
        pipeline_id = "mcq_generation_pipeline"
        model_id = resolve_model(pipeline_id, "default", "chat", local=local)
        request_handler = LlmRequestHandler(model_id=model_id)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=CompletionArguments(temperature=0.7),
        )
        self.pipeline = self.llm | StrOutputParser()

    def __call__(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]] = None,
        language: str = "English",
        callback: Optional[StatusCallback] = None,
        lecture_content: Optional[str] = None,
    ) -> str:
        """
        Generate MCQ questions as a JSON string.

        :param command: Free-text instruction describing what to generate
        :param chat_history: Recent chat history for context
        :param language: Name of the language to write in, such as "German"
        :param callback: Status callback for dynamic chat messages
        :param lecture_content: Pre-retrieved lecture content to base questions on
        :return: JSON string with MCQ data
        """
        if callback:
            callback.update()

        # Build chat history text for template context
        chat_history_text = self._serialize_chat_history(chat_history)

        # Render the prompt
        rendered_prompt = self.prompt_template.render(
            command=command,
            chat_history_text=chat_history_text,
            language=language,
            lecture_content=lecture_content,
        )

        if callback:
            callback.update()

        response = self._invoke(rendered_prompt)

        # Validate JSON
        result = self._extract_and_validate_json(response)
        return result

    def _invoke(self, prompt: str) -> str:
        """Run one model call and record its usage, also when the call stops early."""
        self.llm.tokens = None  # so a call that reports nothing bills nothing
        try:
            return self.pipeline.invoke([SystemMessage(content=prompt)])
        finally:
            if self.llm.tokens is not None:
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_MCQ_GENERATION_PIPELINE
                )

    def generate_set(
        self,
        command: str,
        count: int,
        chat_history: Optional[List[PyrisMessage]] = None,
        language: str = "English",
        lecture_content: Optional[str] = None,
    ) -> str:
        """
        Generate ``count`` questions on distinct subtopics, in parallel.

        :return: JSON string of an ``mcq-set`` with up to ``count`` questions
        :raises ValueError: when no question could be generated
        """
        q: Queue = Queue()
        self._generate_multiple(
            command, chat_history, language, count, q, lecture_content=lecture_content
        )
        questions: list[dict] = []
        while not q.empty():
            kind, data = q.get_nowait()
            if kind != "mcq":
                continue
            parsed = json.loads(data)
            if parsed.get("type") == "mcq-set":
                questions.extend(parsed.get("questions", []))
            else:
                questions.append(parsed)
        if not questions:
            raise ValueError("No MCQ question could be generated")
        return json.dumps({"type": "mcq-set", "questions": questions[:count]})

    def _generate_multiple(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]],
        language: str,
        count: int,
        q: Queue,
        lecture_content: Optional[str] = None,
    ) -> None:
        """Generate multiple MCQ questions in parallel using subtopic extraction.

        1. Fast LLM call to extract N distinct subtopics
        2. Spawn N threads, each generating 1 question for its subtopic
        3. Results are pushed to the queue as they complete

        Falls back to sequential generation if subtopic extraction fails.
        """
        # Step 1: Extract subtopics
        try:
            subtopics = self._extract_subtopics(
                command, chat_history, count, lecture_content=lecture_content
            )
        except Exception as e:
            logger.warning(
                "Subtopic extraction failed, falling back to sequential",
                exc_info=e,
            )
            self._generate_multiple_sequential(
                command,
                chat_history,
                language,
                count,
                q,
                lecture_content=lecture_content,
            )
            return

        # Pad if we got fewer subtopics than requested
        while len(subtopics) < count:
            subtopics.append(
                f"another aspect of the topic (question {len(subtopics) + 1})"
            )

        # Step 2: Create isolated worker pipelines (each has its own LLM instance)
        workers = [McqGenerationPipeline(local=self.local) for _ in range(count)]
        # Each worker needs its OWN context copy — a single Context.run()
        # cannot be called concurrently from multiple threads.
        worker_contexts = [contextvars.copy_context() for _ in range(count)]

        def _generate_one(worker, subtopic, ctx):
            single_command = (
                f"Generate exactly 1 multiple-choice question about: {subtopic}\n"
                f"Use the single MCQ format (type: mcq), NOT mcq-set.\n"
                f"Topic context: {command}"
            )

            def _run():
                return worker(
                    command=single_command,
                    chat_history=chat_history,
                    language=language,
                    callback=None,
                    lecture_content=lecture_content,
                )

            return ctx.run(_run)

        # Step 3: Run in parallel with bounded concurrency
        max_workers = min(count, 10)
        successful_results: list[str] = []
        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="McqWorker"
        ) as pool:
            futures = {
                pool.submit(
                    _generate_one, workers[i], subtopics[i], worker_contexts[i]
                ): i
                for i in range(count)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    successful_results.append(result)
                except Exception as e:
                    logger.error(
                        "MCQ generation failed for question %d of %d",
                        idx + 1,
                        count,
                        exc_info=e,
                    )

        # Retry missing questions sequentially (up to 2 retries per missing)
        missing = count - len(successful_results)
        if missing > 0:
            logger.info("Retrying %d missing MCQ question(s) sequentially", missing)
            for i in range(missing):
                try:
                    result = self(
                        command=f"{command}\n\nGenerate exactly 1 question.",
                        chat_history=chat_history,
                        language=language,
                        callback=None,
                        lecture_content=lecture_content,
                    )
                    successful_results.append(result)
                except Exception as e:
                    logger.error("MCQ retry failed", exc_info=e)

        # Push all successful results to the queue
        for result in successful_results:
            q.put(("mcq", result))

        # Aggregate tokens from worker pipelines
        for worker in workers:
            for token in worker.tokens:
                self.tokens.append(token)
            worker.tokens.clear()

    def _extract_subtopics(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]],
        count: int,
        lecture_content: Optional[str] = None,
    ) -> list[str]:
        """Use a fast LLM call to extract N distinct subtopics for question generation."""
        chat_history_text = self._serialize_chat_history(chat_history)

        prompt = (
            "You are a teaching assistant preparing quiz questions.\n"
            f'Student request: "{command}"\n'
        )
        if chat_history_text:
            prompt += f"\nConversation context:\n{chat_history_text}\n"
        if lecture_content:
            prompt += (
                f"\nLecture material (subtopics MUST come from this material):\n"
                f"{lecture_content}\n"
            )
        prompt += (
            f"\nGenerate exactly {count} distinct subtopics or aspects "
            f"{"from the lecture material above " if lecture_content else ""}"
            f"that would each make a good multiple-choice question. "
            f"Each subtopic should test a different concept or fact.\n"
            f"Respond with ONLY a JSON array of short strings, nothing else. "
            f'Example: ["definition of X", "difference between X and Y", '
            f'"application of Z"]\n'
        )

        response = self._invoke(prompt)

        # Parse response
        cleaned = response.strip()
        if cleaned.startswith("```") and "\n" in cleaned:
            first_newline = cleaned.index("\n")
            last_fence = cleaned.rfind("```")
            if last_fence > first_newline:
                start = first_newline + 1
                cleaned = cleaned[start:last_fence].strip()

        subtopics = json.loads(cleaned)
        if not isinstance(subtopics, list):
            raise ValueError("Expected a JSON array of subtopics")
        return [str(s) for s in subtopics[:count]]

    def _generate_multiple_sequential(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]],
        language: str,
        count: int,
        q: Queue,
        lecture_content: Optional[str] = None,
    ) -> None:
        """Fallback: generate questions sequentially when subtopic extraction fails."""
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
                    language=language,
                    callback=None,
                    lecture_content=lecture_content,
                )
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
        for msg in chat_history[-5:]:
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

        # Repair: auto-fill missing "correct" fields before validation
        _repair_mcq(parsed)

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


def _repair_mcq(mcq: dict) -> None:
    """Auto-repair common LLM omissions so the JSON passes Artemis validation."""
    if mcq.get("type") == "mcq-set":
        for q in mcq.get("questions", []):
            _repair_single_mcq(q)
    else:
        _repair_single_mcq(mcq)


def _repair_single_mcq(mcq: dict) -> None:
    """Fill missing 'correct' fields with False on options that lack them."""
    for opt in mcq.get("options", []):
        if "correct" not in opt:
            opt["correct"] = False


def _validate_single_mcq(mcq: dict) -> None:
    """Validate a single MCQ question structure.

    Ensures the JSON matches what the Artemis client expects:
    - non-empty "question" string
    - "options" array with exactly 4 entries, each with "text" (str) and "correct" (bool)
    - exactly one option with correct=True
    - non-empty "explanation" string
    """
    if "question" not in mcq or not mcq["question"]:
        raise ValueError("MCQ missing 'question' field")
    if "explanation" not in mcq or not mcq["explanation"]:
        raise ValueError("MCQ missing 'explanation' field")
    options = mcq.get("options", [])
    if len(options) != 4:
        raise ValueError(f"MCQ must have exactly 4 options, got {len(options)}")
    for i, opt in enumerate(options):
        if "text" not in opt or not opt["text"]:
            raise ValueError(f"Option {i} missing 'text' field")
        if "correct" not in opt or not isinstance(opt["correct"], bool):
            raise ValueError(f"Option {i} missing or invalid 'correct' field")
    correct_count = sum(1 for opt in options if opt["correct"])
    if correct_count != 1:
        raise ValueError(f"MCQ must have exactly 1 correct option, got {correct_count}")
