import contextvars
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from threading import Thread
from typing import Any, List, Optional, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import StrOutputParser

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import PyrisMessage
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.llm.llm_configuration import resolve_model
from iris.pipeline.sub_pipeline import SubPipeline
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "ein": 1,
    "eins": 1,
    "eine": 1,
    "einen": 1,
    "zwei": 2,
    "drei": 3,
    "vier": 4,
    "fünf": 5,
    "sechs": 6,
    "sieben": 7,
    "acht": 8,
    "neun": 9,
    "zehn": 10,
}
_QUESTION_COUNT_RE = re.compile(
    r"\b(\d{1,2}|" + "|".join(_NUMBER_WORDS) + r")\s+"
    r"(?:(?:multiple[- ]choice|multiple choice)\s+)?"
    r"(?:questions?|mcqs?|quizfragen?|fragen?)\b",
    re.IGNORECASE,
)
_LECTURE_HEADER_RE = re.compile(
    r"^Lecture:\s*.*?,\s*Unit:\s*(?P<unit>.+?),\s*Page\s+[^\n]+$",
    re.IGNORECASE | re.MULTILINE,
)
_DETERMINISTIC_MCQ_ASPECTS = (
    "core concept or factual recall",
    "relationship, reasoning, or implication",
    "application or interpretation",
    "comparison or distinction",
    "condition, boundary, or consequence",
    "worked-example reasoning",
    "terminology and meaning",
    "cause-and-effect relationship",
    "method selection",
    "conceptual misconception check",
)

_ANSWER_PREFIXES = tuple(
    re.sub(r"[^\w+*/=<>-]", "", prefix)
    for prefix in (
        "the answer is",
        "the correct answer is",
        "the correct option is",
        "answer is",
        "correct answer is",
        "correct option is",
        "the result is",
        "the value is",
        "the output is",
        "the state is",
        "the array is",
        "result is",
        "value is",
        "output is",
        "state is",
        "array is",
        "answer:",
        "result:",
        "therefore",
        "thus",
        "hence",
        "die antwort ist",
        "die richtige antwort ist",
        "die richtige option ist",
        "antwort ist",
        "richtige antwort ist",
        "richtige option ist",
        "das ergebnis ist",
        "der wert ist",
        "die ausgabe ist",
        "der zustand ist",
        "das array ist",
        "ergebnis ist",
        "wert ist",
        "ausgabe ist",
        "zustand ist",
        "array ist",
        "antwort:",
        "ergebnis:",
        "daher",
        "deshalb",
        "somit",
    )
)
_CORRECT_SUFFIXES = tuple(
    re.sub(r"[^\w+*/=<>-]", "", suffix)
    for suffix in (
        "is correct",
        "is the correct answer",
        "is the correct option",
        "is right",
        "ist korrekt",
        "ist richtig",
        "ist die richtige antwort",
        "ist die richtige option",
    )
)
_NEGATIVE_PREFIXES = tuple(
    re.sub(r"[^\w+*/=<>-]", "", prefix)
    for prefix in (
        "not",
        "is not",
        "isn't",
        "incorrect",
        "rather than",
        "instead of",
        "unlike",
        "except",
        "nicht",
        "kein",
        "keine",
        "statt",
        "anstatt",
        "anders als",
        "außer",
    )
)
_NEGATIVE_SUFFIXES = tuple(
    re.sub(r"[^\w+*/=<>-]", "", suffix)
    for suffix in (
        "is not correct",
        "is incorrect",
        "is wrong",
        "would be incorrect",
        "would be wrong",
        "is a distractor",
        "is the distractor",
        "is a common distractor",
        "cannot be correct",
        "ist nicht korrekt",
        "ist falsch",
        "wäre falsch",
        "ist ein ablenker",
        "ist die falsche option",
        "kann nicht richtig sein",
    )
)


def _qa_pipeline_retries_disabled() -> bool:
    return os.environ.get("IRIS_QA_DISABLE_PIPELINE_RETRIES") == "1"


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
        jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.prompt_template = jinja_env.get_template("mcq_generation_prompt.j2")

        # Create LLM
        pipeline_id = "mcq_generation_pipeline"
        model_id = resolve_model(pipeline_id, "default", "chat", local=local)
        request_handler = LlmRequestHandler(model_id=model_id)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler,
            completion_args=CompletionArguments(
                temperature=0.2,
                max_tokens=2000,
                response_format=cast(Any, "JSON"),
            ),
        )
        self.pipeline = self.llm | StrOutputParser()

    def __call__(  # type: ignore[override]
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]] = None,
        user_language: str = "en",
        callback: Optional[StatusCallback] = None,
        lecture_content: Optional[str] = None,
        expected_count: Optional[int] = None,
    ) -> str:
        """
        Generate MCQ questions as a JSON string.

        :param command: Free-text instruction describing what to generate
        :param chat_history: Recent chat history for context
        :param user_language: "en" or "de"
        :param callback: Status callback for dynamic chat messages
        :param lecture_content: Pre-retrieved lecture content to base questions on
        :return: JSON string with MCQ data
        """
        if callback:
            callback.update()

        # Build chat history text for template context
        chat_history_text = self._serialize_chat_history(chat_history)

        question_count = expected_count or _question_count_from_command(command)

        # Render the prompt
        rendered_prompt = self.prompt_template.render(
            command=command,
            chat_history_text=chat_history_text,
            user_language=user_language,
            lecture_content=lecture_content,
            question_count=question_count,
        )

        if callback:
            callback.update()

        return self._invoke_validated_mcq(
            rendered_prompt,
            question_count,
            require_source=bool(lecture_content),
            lecture_content=lecture_content,
        )

    def run_in_thread(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]],
        user_language: str,
        result_storage: dict,
        count: int = 1,
        lecture_content: Optional[str] = None,
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
        :param result_storage: Mutable dict for inter-thread communication
        :param count: Number of questions to generate (1 = single, >1 = one-by-one)
        :param lecture_content: Pre-retrieved lecture content to base questions on
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
                        command,
                        chat_history,
                        user_language,
                        count,
                        q,
                        lecture_content=lecture_content,
                    )
                else:
                    result = self(
                        command=command,
                        chat_history=chat_history,
                        user_language=user_language,
                        callback=None,  # pre_agent_hook already sent status
                        lecture_content=lecture_content,
                        expected_count=1,
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
        lecture_content: Optional[str] = None,
    ) -> None:
        """Generate multiple MCQ questions in parallel using subtopic extraction.

        1. Fast LLM call to extract N distinct subtopics
        2. Spawn N threads, each generating 1 question for its subtopic
        3. Results are pushed to the queue as they complete

        Falls back to deterministic aspects if subtopic extraction fails. This
        preserves the already planned N worker calls without launching an
        additional provider-backed fallback path.
        """
        # Step 1: Extract subtopics
        try:
            subtopics = self._extract_subtopics(
                command, chat_history, count, lecture_content=lecture_content
            )
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(
                "Subtopic extraction failed, using deterministic aspects",
                exc_info=e,
            )
            subtopics = _deterministic_mcq_subtopics(
                command,
                count,
                lecture_content=lecture_content,
            )
        except Exception as e:
            if _qa_pipeline_retries_disabled():
                raise RuntimeError(
                    "QA MCQ subtopic generation failed; fallback calls are disabled"
                ) from e
            logger.warning(
                "Subtopic provider call failed, falling back to sequential",
                exc_info=e,
            )
            self._generate_multiple_sequential(
                command,
                chat_history,
                user_language,
                count,
                q,
                lecture_content=lecture_content,
            )
            return

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
                    user_language=user_language,
                    callback=None,
                    lecture_content=lecture_content,
                    expected_count=1,
                )

            return ctx.run(_run)

        # Step 3: Run in parallel with bounded concurrency
        max_workers = min(count, 10)
        successful_results: dict[int, str] = {}
        generation_errors: dict[int, Exception] = {}
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
                    successful_results[idx] = result
                except Exception as e:
                    generation_errors[idx] = e
                    logger.error(
                        "MCQ generation failed for question %d of %d",
                        idx + 1,
                        count,
                        exc_info=e,
                    )

        if generation_errors:
            first_index = min(generation_errors)
            first_error = generation_errors[first_index]
            raise RuntimeError(
                "MCQ generation failed for question "
                f"{first_index + 1} after its bounded validation repair: "
                f"{type(first_error).__name__}: {first_error}"
            ) from first_error

        # Preserve the requested subtopic order, regardless of worker completion order.
        for index in range(count):
            q.put(("mcq", successful_results[index]))

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
            f"Respond with ONLY a JSON object with one field named subtopics. "
            f'Example: {{"subtopics":["definition of X",'
            f'"difference between X and Y","application of Z"]}}\n'
        )

        def validate(response: str) -> list[str]:
            parsed = _parse_json_object(response)
            if set(parsed) != {"subtopics"}:
                raise ValueError("Subtopic JSON must contain only 'subtopics'")
            subtopics = parsed["subtopics"]
            if not isinstance(subtopics, list) or len(subtopics) != count:
                raise ValueError(f"Expected exactly {count} subtopics")
            if any(not isinstance(item, str) or not item.strip() for item in subtopics):
                raise ValueError("Every subtopic must be a non-empty string")
            normalized = [item.strip() for item in subtopics]
            if len({item.casefold() for item in normalized}) != count:
                raise ValueError("Subtopics must be distinct")
            return normalized

        return self._invoke_structured(prompt, validate, "subtopic object")

    def _generate_multiple_sequential(
        self,
        command: str,
        chat_history: Optional[List[PyrisMessage]],
        user_language: str,
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
                    user_language=user_language,
                    callback=None,
                    lecture_content=lecture_content,
                    expected_count=1,
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

    def _invoke_validated_mcq(
        self,
        rendered_prompt: str,
        expected_count: int,
        *,
        require_source: bool,
        lecture_content: Optional[str] = None,
    ) -> str:
        """Generate, then independently verify one structurally valid MCQ payload."""

        def validate(response: str) -> str:
            return self._extract_and_validate_json(
                response,
                expected_count,
                require_source=require_source,
                lecture_content=lecture_content,
            )

        candidate = self._invoke_structured(rendered_prompt, validate, "MCQ object")
        verification_prompt = (
            "You are the final correctness reviewer for an educational MCQ.\n"
            "Solve every question yourself before returning it. Return only one "
            "JSON object in exactly the same required shape and item count.\n"
            "Correct any wrong answer key or explanation. If a question is ambiguous, "
            "depends on an unstated implementation variant, or asks for an exact "
            "operation count that the supplied evidence does not establish, replace "
            "it with an unambiguous question about the same requested topic and "
            "difficulty. Keep exactly four distinct options and one correct option.\n"
            "When lecture material is supplied, use only that material and preserve "
            "an exact retrieved lecture-unit source for every question. Do not add "
            "facts from outside it.\n\n"
            f"Original task, schema, and evidence:\n{rendered_prompt}\n\n"
            f"Candidate MCQ to verify:\n{candidate}"
        )
        return self._invoke_structured(
            verification_prompt,
            validate,
            "verified MCQ object",
        )

    def _invoke_structured(self, prompt: str, validator, label: str):
        response = self.pipeline.invoke([SystemMessage(content=prompt)])
        self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_MCQ_GENERATION_PIPELINE)
        try:
            return validator(response)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            if _qa_pipeline_retries_disabled():
                if isinstance(error, ValueError) and not isinstance(
                    error, json.JSONDecodeError
                ):
                    diagnostic = _mcq_validation_diagnostic(response)
                    raise ValueError(
                        f"{error}; invalid structured output: {diagnostic}"
                    ) from error
                raise
            repair_prompt = (
                f"{prompt}\n\nThe previous {label} failed validation: {error}.\n"
                "Return one corrected JSON object only. Preserve the requested "
                "content and exact item count; do not add commentary.\n"
                f"Previous invalid output:\n{response}"
            )
            repaired = self.pipeline.invoke([SystemMessage(content=repair_prompt)])
            self._append_tokens(
                self.llm.tokens, PipelineEnum.IRIS_MCQ_GENERATION_PIPELINE
            )
            return validator(repaired)

    @staticmethod
    def _extract_and_validate_json(
        response: str,
        expected_count: int = 1,
        *,
        require_source: bool = False,
        lecture_content: Optional[str] = None,
    ) -> str:
        """Extract and validate MCQ JSON from the LLM response."""
        parsed = _parse_json_object(response)
        parsed = _normalize_mcq_envelope(parsed, expected_count)
        lecture_sources = _lecture_source_blocks(lecture_content)
        if lecture_sources:
            _normalize_lecture_sources(parsed, lecture_sources)

        # Validate structure
        mcq_type = parsed.get("type")
        if mcq_type == "mcq":
            if expected_count != 1:
                raise ValueError(
                    f"Expected exactly {expected_count} questions in an mcq-set"
                )
            _validate_single_mcq(parsed, require_source=require_source)
            _validate_lecture_source(parsed, lecture_sources)
        elif mcq_type == "mcq-set":
            if set(parsed) != {"type", "questions"}:
                raise ValueError("mcq-set contains unknown or missing fields")
            questions = parsed["questions"]
            if not isinstance(questions, list) or len(questions) != expected_count:
                raise ValueError(
                    f"mcq-set must contain exactly {expected_count} questions"
                )
            for q in questions:
                _validate_single_mcq(
                    q,
                    nested=True,
                    require_source=require_source,
                )
                _validate_lecture_source(q, lecture_sources)
        else:
            raise ValueError(f"Unknown MCQ type: {mcq_type}")

        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _parse_json_object(response: str) -> dict:
    """Deterministically unwrap an optional fence and require one JSON object."""
    cleaned = response.strip()
    if cleaned.startswith("```") and "\n" in cleaned:
        first_newline = cleaned.index("\n")
        last_fence = cleaned.rfind("```")
        if last_fence <= first_newline:
            raise ValueError("Unclosed JSON markdown fence")
        cleaned = cleaned[first_newline + 1 : last_fence].strip()
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Structured output must be one JSON object")
    return parsed


def _mcq_validation_diagnostic(response: str) -> str:
    """Put answer evidence first in bounded QA-only validation diagnostics."""

    cleaned = response.strip().replace("\x00", "")
    try:
        parsed = _parse_json_object(cleaned)
    except (json.JSONDecodeError, TypeError, ValueError):
        return cleaned[:2000]
    questions = parsed.get("questions")
    question = questions[0] if isinstance(questions, list) and questions else parsed
    if not isinstance(question, dict):
        return cleaned[:2000]
    evidence = {
        "explanation": question.get("explanation"),
        "options": question.get("options"),
        "question": question.get("question"),
    }
    return json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))[:2000]


def _normalize_mcq_envelope(parsed: dict, expected_count: int) -> dict:
    """Normalize equivalent discriminator/envelope shapes without changing content."""

    if expected_count == 1 and parsed.get("type") == "mcq-set":
        questions = parsed.get("questions")
        if set(parsed) == {"type", "questions"} and isinstance(questions, list):
            if len(questions) == 1 and isinstance(questions[0], dict):
                question = dict(questions[0])
                if question.get("type") in (None, "mcq"):
                    question["type"] = "mcq"
                    return question

    if "type" not in parsed:
        single_fields = {"question", "options", "explanation", "source"}
        if {"question", "options", "explanation"}.issubset(parsed) and set(
            parsed
        ).issubset(single_fields):
            return {"type": "mcq", **parsed}
        if set(parsed) == {"questions"} and isinstance(parsed["questions"], list):
            return {"type": "mcq-set", **parsed}

    return parsed


def _lecture_source_blocks(
    lecture_content: Optional[str],
) -> list[tuple[str, str]]:
    """Return exact lecture unit names and their associated trusted text."""

    if not lecture_content:
        return []
    matches = list(_LECTURE_HEADER_RE.finditer(lecture_content))
    aggregated: dict[str, list[str]] = {}
    for index, match in enumerate(matches):
        unit = match.group("unit").strip()
        if not unit:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else None
        body = lecture_content[match.end() : end].strip()
        aggregated.setdefault(unit, []).append(body)
    return [(unit, "\n".join(parts)) for unit, parts in aggregated.items()]


def _deterministic_mcq_subtopics(
    command: str,
    count: int,
    *,
    lecture_content: Optional[str] = None,
) -> list[str]:
    """Create distinct, evidence-scoped worker aspects without another LLM call."""

    unit_names = [unit for unit, _ in _lecture_source_blocks(lecture_content)]
    requested_topic = command.strip() or "the requested topic"
    subtopics: list[str] = []
    for index in range(count):
        aspect = _DETERMINISTIC_MCQ_ASPECTS[index]
        if unit_names:
            unit = unit_names[index % len(unit_names)]
            subtopics.append(f"{aspect} from lecture unit {unit!r}")
        else:
            subtopics.append(f"{aspect} for: {requested_topic}")
    return subtopics


def _normalize_lecture_sources(
    parsed: dict,
    lecture_sources: list[tuple[str, str]],
) -> None:
    """Canonicalize a source only when retrieved evidence identifies it uniquely."""

    questions = (
        parsed.get("questions", []) if parsed.get("type") == "mcq-set" else [parsed]
    )
    canonical = {
        re.sub(r"\s+", " ", unit).strip().casefold(): unit
        for unit, _ in lecture_sources
    }
    for question in questions:
        if not isinstance(question, dict):
            continue
        source = question.get("source")
        if isinstance(source, str) and source.strip():
            key = re.sub(r"\s+", " ", source).strip().casefold()
            if key in canonical:
                question["source"] = canonical[key]
            continue
        inferred = _infer_lecture_source(question, lecture_sources)
        if inferred is not None:
            question["source"] = inferred


def _infer_lecture_source(
    question: dict,
    lecture_sources: list[tuple[str, str]],
) -> Optional[str]:
    """Infer an omitted source only from a unique lexical evidence match."""

    if len(lecture_sources) == 1:
        return lecture_sources[0][0]
    question_text = " ".join(
        [
            str(question.get("question", "")),
            str(question.get("explanation", "")),
            *[
                str(option.get("text", ""))
                for option in question.get("options", [])
                if isinstance(option, dict)
            ],
        ]
    )
    question_terms = _source_match_terms(question_text)
    scores = [
        len(question_terms & _source_match_terms(f"{unit} {body}"))
        for unit, body in lecture_sources
    ]
    if not scores:
        return None
    highest = max(scores)
    if highest < 2 or scores.count(highest) != 1:
        return None
    return lecture_sources[scores.index(highest)][0]


def _source_match_terms(value: str) -> set[str]:
    stopwords = {
        "about",
        "answer",
        "because",
        "correct",
        "does",
        "from",
        "lecture",
        "question",
        "the",
        "this",
        "unit",
        "which",
        "antwort",
        "diese",
        "dieser",
        "frage",
        "richtig",
        "vorlesung",
        "welche",
    }
    return {
        term
        for term in re.findall(r"[^\W\d_]{4,}", value.casefold())
        if term not in stopwords
    }


def _validate_lecture_source(
    question: dict,
    lecture_sources: list[tuple[str, str]],
) -> None:
    if not lecture_sources:
        return
    allowed = {unit for unit, _ in lecture_sources}
    if question.get("source") not in allowed:
        raise ValueError("MCQ 'source' must exactly match a retrieved lecture unit")


def _question_count_from_command(command: str) -> int:
    """Read an explicit English or German question count, defaulting to one."""
    match = _QUESTION_COUNT_RE.search(command)
    if not match:
        return 1
    raw = match.group(1).casefold()
    count = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    if not 1 <= count <= 10:
        raise ValueError("MCQ question count must be between 1 and 10")
    return count


def _validate_single_mcq(
    mcq: dict,
    *,
    nested: bool = False,
    require_source: bool = False,
) -> None:
    """Validate a question and reconcile its key with an explicit explanation.

    Ensures the JSON matches what the Artemis client expects:
    - non-empty "question" string
    - "options" array with exactly 4 entries, each with "text" (str) and "correct" (bool)
    - exactly one option with correct=True
    - non-empty "explanation" string
    """
    if not isinstance(mcq, dict):
        raise ValueError("Each MCQ question must be a JSON object")
    allowed = {"question", "options", "explanation", "source"}
    if not nested:
        allowed.add("type")
        if mcq.get("type") != "mcq":
            raise ValueError("Single MCQ must have type 'mcq'")
    elif "type" in mcq:
        allowed.add("type")
        if mcq["type"] != "mcq":
            raise ValueError("Nested MCQ type must be 'mcq' when present")
    required = {"question", "options", "explanation"}
    if require_source:
        required.add("source")
    if not required.issubset(mcq) or not set(mcq).issubset(allowed):
        raise ValueError("MCQ contains unknown or missing fields")
    if not isinstance(mcq["question"], str) or not mcq["question"].strip():
        raise ValueError("MCQ missing 'question' field")
    if not isinstance(mcq["explanation"], str) or not mcq["explanation"].strip():
        raise ValueError("MCQ missing 'explanation' field")
    if "source" in mcq and (
        not isinstance(mcq["source"], str) or not mcq["source"].strip()
    ):
        raise ValueError("MCQ 'source' must be a non-empty string")
    options = mcq["options"]
    if not isinstance(options, list):
        raise ValueError("MCQ 'options' must be an array")
    if len(options) != 4:
        raise ValueError(f"MCQ must have exactly 4 options, got {len(options)}")
    for i, opt in enumerate(options):
        if not isinstance(opt, dict) or set(opt) != {"text", "correct"}:
            raise ValueError(f"Option {i} contains unknown or missing fields")
        if not isinstance(opt["text"], str) or not opt["text"].strip():
            raise ValueError(f"Option {i} missing 'text' field")
        if not isinstance(opt["correct"], bool):
            raise ValueError(f"Option {i} missing or invalid 'correct' field")
    normalized_options = [_normalize_answer_text(opt["text"]) for opt in options]
    if any(not option for option in normalized_options):
        raise ValueError("Every MCQ option must contain a meaningful answer")
    if len(set(normalized_options)) != len(normalized_options):
        raise ValueError("MCQ options must be distinct after normalization")
    correct_count = sum(1 for opt in options if opt["correct"])
    if correct_count != 1:
        raise ValueError(f"MCQ must have exactly 1 correct option, got {correct_count}")

    explanation_matches, explanation_negations = _explanation_option_evidence(
        mcq["explanation"],
        normalized_options,
        [option["text"] for option in options],
    )
    if len(explanation_matches) > 1:
        raise ValueError(
            "MCQ explanation identifies multiple existing options as correct"
        )
    if not explanation_matches:
        # A well-formed key plus an explanation that does not name any option is
        # incomplete consistency evidence, not evidence of a contradiction. Keep
        # the existing key; never invent or rewrite explanatory content here.
        marked_index = next(i for i, option in enumerate(options) if option["correct"])
        if marked_index in explanation_negations:
            raise ValueError("MCQ explanation contradicts the marked correct option")
        return

    explained_index = explanation_matches[0]
    marked_index = next(i for i, option in enumerate(options) if option["correct"])
    if explained_index in explanation_negations:
        raise ValueError("MCQ explanation contains conflicting claims about its answer")
    if marked_index != explained_index:
        logger.warning(
            "Repairing inconsistent MCQ answer key from option %d to option %d",
            marked_index,
            explained_index,
        )
        for i, option in enumerate(options):
            option["correct"] = i == explained_index


def _normalize_answer_text(value: str) -> str:
    """Normalize option/explanation fragments without erasing math semantics."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(
        r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
        r"\1/\2",
        normalized,
    )
    normalized = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt\1", normalized)
    normalized = re.sub(
        r"\\(?:text|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}",
        r"\1",
        normalized,
    )
    normalized = re.sub(r"\\([a-z]+)", r"\1", normalized)
    normalized = normalized.replace("**", "").replace("__", "")
    normalized = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", normalized)
    normalized = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", normalized)
    for source, replacement in (
        ("−", "-"),
        ("–", "-"),
        ("—", "-"),
        ("×", "*"),
        ("·", "*"),
        ("÷", "/"),
        ("≤", "<="),
        ("≥", ">="),
        ("√", "sqrt"),
        ("α", "alpha"),
        ("β", "beta"),
        ("γ", "gamma"),
        ("δ", "delta"),
        ("θ", "theta"),
        ("λ", "lambda"),
        ("μ", "mu"),
        ("π", "pi"),
        ("σ", "sigma"),
        ("ω", "omega"),
    ):
        normalized = normalized.replace(source, replacement)
    normalized = re.sub(r"(?<=[^\W\d_])\s*-\s*(?=[^\W\d_])", "", normalized)
    return re.sub(r"[^\w+*/=<>-]", "", normalized)


def _explanation_option_evidence(
    explanation: str, normalized_options: list[str], raw_options: list[str]
) -> tuple[list[int], list[int]]:
    """Return answer candidates and options explicitly presented as incorrect.

    Matching is deliberately assertion-based rather than simple substring matching:
    an option discussed as a distractor must not silently become the answer key.
    """

    normalized_explanation = _normalize_answer_text(explanation)
    mentions: list[tuple[int, int, str]] = []
    for index, option in enumerate(normalized_options):
        start = 0
        while True:
            position = normalized_explanation.find(option, start)
            if position < 0:
                break
            prefix = normalized_explanation[:position]
            suffix = normalized_explanation[position + len(option) :]
            negative = any(prefix.endswith(item) for item in _NEGATIVE_PREFIXES) or any(
                suffix.startswith(item) for item in _NEGATIVE_SUFFIXES
            )
            positive = any(prefix.endswith(item) for item in _ANSWER_PREFIXES) or any(
                suffix.startswith(item) for item in _CORRECT_SUFFIXES
            )
            if negative:
                mentions.append((index, position, "negative"))
            elif positive:
                mentions.append((index, position, "explicit"))
            elif _allow_implicit_option_match(explanation, option, raw_options[index]):
                mentions.append((index, position, "implicit"))
            start = position + max(1, len(option))

    retained = _remove_shadowed_option_mentions(mentions, normalized_options)
    explicit_matches = _unique_option_indices(retained, classification="explicit")
    answer_matches = explicit_matches or _unique_option_indices(
        retained, classification="implicit"
    )
    negative_matches = _unique_option_indices(retained, classification="negative")
    return answer_matches, negative_matches


def _allow_implicit_option_match(
    explanation: str, normalized_option: str, raw_option: str
) -> bool:
    """Exclude substring coincidences for very short scalar options."""

    if len(normalized_option) == 1 and normalized_option.isalpha():
        return False
    if normalized_option.isdigit() and re.fullmatch(
        r"\s*[+-]?\d+\s*", unicodedata.normalize("NFKC", raw_option)
    ):
        normalized_explanation = unicodedata.normalize("NFKC", explanation).casefold()
        return bool(
            re.search(
                rf"(?<!\d){re.escape(normalized_option)}(?!\d)",
                normalized_explanation,
            )
        )
    return True


def _remove_shadowed_option_mentions(
    mentions: list[tuple[int, int, str]], normalized_options: list[str]
) -> list[tuple[int, int, str]]:
    """Prefer the longest exact option when normalized option texts overlap."""

    return [
        mention
        for mention in mentions
        if not any(
            other[1] == mention[1]
            and len(normalized_options[other[0]]) > len(normalized_options[mention[0]])
            and normalized_options[other[0]].startswith(normalized_options[mention[0]])
            for other in mentions
        )
    ]


def _unique_option_indices(
    mentions: list[tuple[int, int, str]], *, classification: str
) -> list[int]:
    return list(
        dict.fromkeys(item[0] for item in mentions if item[2] == classification)
    )
