import contextvars
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from typing import Any, Callable, List, Optional

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

# The quiz tool returns this; the chat replaces it with the quiz JSON.
MCQ_PLACEHOLDER = "[MCQ_RESULT]"


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
        Generate one MCQ question as a JSON string.

        :param command: Free-text instruction describing what to generate
        :param chat_history: Recent chat history for context
        :param language: Name of the language to write in, such as "German"
        :param callback: Status callback for dynamic chat messages
        :param lecture_content: Pre-retrieved lecture content to base questions on
        :return: JSON string of a single ``mcq`` question
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
        subtopics = self._decode_json_values(response, accept=_is_subtopic_list)[0]
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
    def _decode_json_values(
        response: str, accept: Callable[[Any], bool] = lambda _value: True
    ) -> list:
        """Decode the consecutive top-level JSON values the model returned.

        Scans for the first ``{`` or ``[`` whose value decodes and passes
        ``accept``, so markdown fences and leading prose are skipped, even
        prose with brackets such as "Here is question [1]:". Then collects the
        objects or arrays that directly follow, separated by whitespace or
        commas. The first text that is not one ends the scan, so trailing
        prose is ignored even when it starts like a JSON scalar ("2 more
        questions"). A value that fails to decode is searched from its next
        character, so the first complete value inside it (such as question 1
        of an array with a missing comma) is used, with a warning. Raises a
        JSON error (or ValueError) when no acceptable value is found, so the
        caller can log the raw response.
        """
        decoder = json.JSONDecoder()
        first_error: Optional[json.JSONDecodeError] = None
        start = _first_json_index(response)
        while start is not None:
            try:
                value, end = decoder.raw_decode(response, start)
            except json.JSONDecodeError as error:
                # The first parse error is the most useful one to report.
                first_error = first_error or error
                # Search inside the broken value too, so an array with a missing
                # comma yields its first complete question, not a later one.
                resume = start + 1
            else:
                if accept(value):
                    if first_error is not None:
                        logger.warning(
                            "Skipped malformed JSON before the usable value: %s",
                            first_error,
                        )
                    return [value, *_following_values(decoder, response, end, accept)]
                resume = end
            start = _first_json_index(response, resume)

        if first_error is not None:
            raise first_error
        # Plain text gets json's precise decode error; anything else is unusable.
        json.loads(response.strip())
        raise ValueError("Response contained no usable JSON object or array")

    @staticmethod
    def _flatten_questions(values: list) -> list:
        """Turn decoded JSON values into a flat list of question dicts.

        Accepts single ``mcq`` objects, ``mcq-set`` objects and bare arrays, in
        any combination, so several of them in a row become one quiz.
        """
        questions: list = []
        for value in values:
            if isinstance(value, list):
                items = value
            elif _is_mcq_set(value):
                items = value.get("questions")
                if items is None:
                    items = []
                elif not isinstance(items, list):
                    raise ValueError(f"MCQ 'questions' must be an array, got {items!r}")
            elif isinstance(value, dict):
                items = [value]
            else:
                raise ValueError(f"Unexpected MCQ JSON value: {value!r}")
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError(f"MCQ question must be an object, got {item!r}")
                questions.append(item)
        return questions

    @staticmethod
    def _extract_and_validate_json(response: str) -> str:
        """Extract and validate MCQ JSON from the LLM response.

        The model does not always return exactly one JSON object: it may emit
        several questions in a row, a top-level array, or JSON followed by a
        sentence. We collect every consecutive JSON value, ignore trailing
        prose and flatten them into questions. Every caller asks for exactly
        one question, so only the first is kept and returned as an ``mcq``;
        any others are dropped with a warning.
        """
        try:
            questions = McqGenerationPipeline._flatten_questions(
                McqGenerationPipeline._decode_json_values(
                    response, accept=_is_mcq_value
                )
            )
        except ValueError:
            logger.warning("Could not parse MCQ JSON from response: %r", response)
            raise

        if not questions:
            logger.warning("Response contained no MCQ question: %r", response)
            raise ValueError("Response contained no MCQ question")

        if len(questions) > 1:
            logger.warning(
                "Model returned %d MCQ questions where 1 was requested; "
                "keeping the first",
                len(questions),
            )
        question = questions[0]

        # Array items may omit "type", but an explicit other type is not an MCQ.
        mcq_type = question.get("type", "mcq")
        if mcq_type != "mcq":
            logger.warning("Response contained an unknown MCQ type: %r", response)
            raise ValueError(f"Unknown MCQ type: {mcq_type}")

        try:
            _repair_single_mcq(question)
            _validate_single_mcq(question)
        except ValueError:
            logger.warning("MCQ JSON failed validation; response: %r", response)
            raise

        return json.dumps({**question, "type": "mcq"})


def _first_json_index(text: str, start: int = 0) -> Optional[int]:
    """Index of the first ``{`` or ``[`` at or after ``start``, or ``None``."""
    indices = [i for i in (text.find("{", start), text.find("[", start)) if i != -1]
    return min(indices) if indices else None


def _following_values(
    decoder: json.JSONDecoder, text: str, index: int, accept: Callable[[Any], bool]
) -> list:
    """The acceptable objects or arrays right after ``index``.

    Values may be separated by whitespace or commas (``{...},\\n{...}``). Only
    an object or array continues the scan, so a sentence after the JSON (even
    "2 more questions" or "\\"Good luck!\\"") is ignored, not decoded.
    """
    values: list = []
    while True:
        while index < len(text) and (text[index].isspace() or text[index] == ","):
            index += 1
        if index >= len(text) or text[index] not in "{[":
            return values
        try:
            value, index = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            return values
        if not accept(value):
            return values
        values.append(value)


def _is_mcq_value(value: Any) -> bool:
    """Whether a decoded value holds MCQ questions.

    Matches what ``_flatten_questions`` expands: a question object, an
    ``mcq-set`` object, or a non-empty list of question objects. Other objects,
    such as metadata with a ``questions`` key, are skipped.
    """
    if isinstance(value, list):
        return bool(value) and all(_is_question(item) for item in value)
    return _is_question(value) or _is_mcq_set(value)


def _is_question(value: Any) -> bool:
    """Whether a value is an object with a ``question`` key."""
    return isinstance(value, dict) and "question" in value


def _is_mcq_set(value: Any) -> bool:
    """Whether a value is an object of type ``mcq-set``."""
    return isinstance(value, dict) and value.get("type") == "mcq-set"


def _is_subtopic_list(value: Any) -> bool:
    """Whether a decoded value is a non-empty list of subtopic strings."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) for item in value)
    )


def _repair_single_mcq(mcq: dict) -> None:
    """Fill missing 'correct' fields with False on options that lack them.

    Malformed options are left alone for ``_validate_single_mcq`` to report.
    """
    options = mcq.get("options", [])
    if not isinstance(options, list):
        return
    for opt in options:
        if isinstance(opt, dict) and "correct" not in opt:
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
    if not isinstance(options, list):
        raise ValueError(f"MCQ 'options' must be an array, got {options!r}")
    if len(options) != 4:
        raise ValueError(f"MCQ must have exactly 4 options, got {len(options)}")
    for i, opt in enumerate(options):
        if not isinstance(opt, dict):
            raise ValueError(f"Option {i} must be an object, got {opt!r}")
        if "text" not in opt or not opt["text"]:
            raise ValueError(f"Option {i} missing 'text' field")
        if "correct" not in opt or not isinstance(opt["correct"], bool):
            raise ValueError(f"Option {i} missing or invalid 'correct' field")
    correct_count = sum(1 for opt in options if opt["correct"])
    if correct_count != 1:
        raise ValueError(f"MCQ must have exactly 1 correct option, got {correct_count}")
