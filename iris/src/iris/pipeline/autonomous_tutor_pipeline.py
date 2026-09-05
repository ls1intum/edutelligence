import os
from typing import Callable, List, Tuple, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from iris.common.logging_config import get_logger
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.config import settings
from iris.domain.autonomous_tutor.autonomous_tutor_pipeline_execution_dto import (
    AutonomousTutorPipelineExecutionDTO,
)
from iris.domain.data.post_dto import PostDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.variant.variant import Dep, Variant
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.pipeline.shared.confidence_scoring import (
    is_large_model,
    logprob_confidence,
    model_supports_logprobs,
    parse_confidence_response,
)
from iris.pipeline.shared.organizational_guard import (
    classify_organizational_question,
    has_organizational_evidence,
    tutor_verified_memory_hits,
)
from iris.pipeline.shared.uncertainty_scoring import (
    DEFAULT_TOP_LOGPROBS,
    uncertainty_confidence,
)
from iris.pipeline.shared.utils import (
    REDACTED_ANSWER_PLACEHOLDER,
    get_current_utc_datetime_string,
)
from iris.retrieval.course_memory_retrieval import CourseMemoryRetrieval
from iris.retrieval.course_memory_retrieval_utils import (
    should_allow_course_memory_tool,
)
from iris.retrieval.faq_retrieval import FaqRetrieval
from iris.retrieval.faq_retrieval_utils import should_allow_faq_tool
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.tools import (
    create_tool_course_memory_retrieval,
    create_tool_faq_content_retrieval,
    create_tool_get_additional_exercise_details,
    create_tool_get_example_solution,
    create_tool_get_problem_statement,
    create_tool_get_simple_course_details,
    create_tool_lecture_content_retrieval,
)
from iris.tracing import observe
from iris.web.status.status_update import AutonomousTutorCallback

logger = get_logger(__name__)

# Author role Artemis assigns to Iris's own replies in a thread.
IRIS_AUTHOR_ROLE = "IRIS"

# Human-readable labels prefixed to each thread message so the model can tell the
# participants apart. Roles are supplied by Artemis; unknown/missing roles fall back
# to a neutral label rather than silently claiming the author is a student.
AUTHOR_ROLE_LABELS = {
    IRIS_AUTHOR_ROLE: "Iris (you)",
    "INSTRUCTOR": "Instructor",
    "TUTOR": "Tutor",
    "STUDENT": "Student",
}
UNKNOWN_AUTHOR_LABEL = "Course member"


class AutonomousTutorPipeline(
    AbstractAgentPipeline[AutonomousTutorPipelineExecutionDTO, Variant]
):
    """
    The AutonomousTutorPipeline autonomously responds to student posts.
    It analyzes the post and generates a helpful response based on available context.
    """

    PIPELINE_ID = "autonomous_tutor_pipeline"
    ROLES = {"chat"}
    VARIANT_DEFS = [
        (
            "default",
            "Default",
            "Default autonomous tutor variant.",
        ),
    ]
    DEPENDENCIES = [
        Dep("lecture_retrieval_pipeline"),
        Dep("lecture_unit_segment_retrieval_pipeline"),
        Dep("lecture_transcriptions_retrieval_pipeline"),
        Dep("faq_retrieval_pipeline"),
        Dep("course_memory_retrieval_pipeline"),
    ]

    def __init__(self):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.lecture_retriever = None
        self.faq_retriever = None
        self.course_memory_retriever = None

        template_dir = os.path.join(os.path.dirname(__file__), "prompts", "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "autonomous_tutor_system_prompt.j2"
        )
        self.confidence_combo_template = self.jinja_env.get_template(
            "autonomous_tutor_confidence_combo.j2"
        )
        self.confidence_basic_template = self.jinja_env.get_template(
            "autonomous_tutor_confidence_basic.j2"
        )

        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}"

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> list[Callable]:
        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)
        allow_faq_tool = should_allow_faq_tool(state.db, state.dto.course.id)
        allow_course_memory_tool = should_allow_course_memory_tool(
            state.db, state.dto.course.id
        )
        is_programming_exercise = state.dto.programming_exercise is not None
        is_text_exercise = state.dto.text_exercise is not None

        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})
        if not hasattr(state, "memory_storage"):
            setattr(state, "memory_storage", {})

        callback = state.callback
        if not isinstance(callback, AutonomousTutorCallback):
            callback = cast(AutonomousTutorCallback, state.callback)

        tool_list: List[Callable] = []
        if is_programming_exercise:
            tool_list.extend(
                [
                    create_tool_get_problem_statement(
                        state.dto.programming_exercise, callback
                    ),
                    create_tool_get_additional_exercise_details(
                        state.dto.programming_exercise, callback
                    ),
                ]
            )

        if is_text_exercise:
            tool_list.extend(
                [
                    create_tool_get_problem_statement(
                        state.dto.text_exercise, callback
                    ),
                    create_tool_get_example_solution(state.dto.text_exercise, callback),
                ]
            )

        query_text = self._generate_retrieval_query_text(state.dto.post)

        if allow_lecture_tool:
            self.lecture_retriever = LectureRetrieval(
                state.db.client,
                local=state.dto.settings is not None and state.dto.settings.is_local(),
            )
            tool_list.append(
                create_tool_lecture_content_retrieval(
                    self.lecture_retriever,
                    state.dto.course.id,
                    (state.dto.settings.artemis_base_url if state.dto.settings else ""),
                    callback,
                    query_text,
                    state.message_history,
                    getattr(state, "lecture_content_storage", {}),
                )
            )

        if allow_faq_tool:
            self.faq_retriever = FaqRetrieval(
                state.db.client,
                local=state.dto.settings is not None and state.dto.settings.is_local(),
            )
            tool_list.append(
                create_tool_faq_content_retrieval(
                    self.faq_retriever,
                    state.dto.course.id,
                    state.dto.course.name,
                    (state.dto.settings.artemis_base_url if state.dto.settings else ""),
                    callback,
                    query_text,
                    state.message_history,
                    getattr(state, "faq_storage", {}),
                )
            )

        if allow_course_memory_tool:
            self.course_memory_retriever = CourseMemoryRetrieval(
                state.db.client,
                local=state.dto.settings is not None and state.dto.settings.is_local(),
            )
            tool_list.append(
                create_tool_course_memory_retrieval(
                    self.course_memory_retriever,
                    state.dto.course.id,
                    state.dto.course.name,
                    (state.dto.settings.artemis_base_url if state.dto.settings else ""),
                    callback,
                    query_text,
                    state.message_history,
                    getattr(state, "memory_storage", {}),
                )
            )

        tool_list.append(
            create_tool_get_simple_course_details(state.dto.course, callback)
        )

        return tool_list

    def prepare_state(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> None:
        """Select the confidence strategy before generation.

        When the selected model exposes token-level log-probabilities, the
        pipeline derives confidence directly from them (thesis §6.6) and
        requests logprobs on the generation call. Otherwise it falls back to
        the verbalized strategy, whose confidence prompt is appended to the
        system message by build_system_message.
        """
        model_id = state.llm.model_name if state.llm else ""
        use_logprob = model_supports_logprobs(model_id)
        state.use_logprob_confidence = use_logprob
        if use_logprob and state.llm is not None:
            state.llm.completion_args.logprobs = True
            # Top-k alternatives enable the uncertainty method (Xu et al.,
            # FSE '25); backends without top_logprobs support degrade to the
            # mean-logprob strategy (see supports_top_logprobs in llm_config).
            state.llm.completion_args.top_logprobs = DEFAULT_TOP_LOGPROBS
            logger.info("Using logprob confidence strategy | model=%s", model_id)

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> str:
        post = state.dto.post
        target_label, target_content = self._target_message(post)
        has_thread_context = bool(post and post.answers)

        template_context = {
            "current_date": get_current_utc_datetime_string(),
            "allow_lecture_tool": should_allow_lecture_tool(
                state.db, state.dto.course.id
            ),
            "allow_faq_tool": should_allow_faq_tool(state.db, state.dto.course.id),
            "allow_course_memory_tool": should_allow_course_memory_tool(
                state.db, state.dto.course.id
            ),
            "is_programming_exercise": state.dto.programming_exercise is not None,
            "is_text_exercise": state.dto.text_exercise is not None,
            "target_author": target_label,
            "target_message": target_content or "No message content provided.",
            "target_is_own_message": target_label
            == AUTHOR_ROLE_LABELS[IRIS_AUTHOR_ROLE],
            "has_thread_context": has_thread_context,
            "course_name": (
                state.dto.course.name
                if state.dto.course and state.dto.course.name
                else "the course"
            ),
        }
        base_prompt = self.system_prompt_template.render(template_context)
        # In logprob mode the model simply answers; confidence comes from the
        # token log-probabilities, so no verbalized confidence prompt is added.
        if getattr(state, "use_logprob_confidence", False):
            return base_prompt
        model_id = state.llm.model_name if state.llm else ""
        if is_large_model(model_id):
            logger.info("Using combo confidence prompt | model=%s", model_id)
            confidence_section = self.confidence_combo_template.render()
        else:
            logger.info("Using basic confidence prompt | model=%s", model_id)
            confidence_section = self.confidence_basic_template.render()
        return base_prompt + "\n\n" + confidence_section

    def get_memiris_tenant(self, dto: AutonomousTutorPipelineExecutionDTO) -> str:
        """
        Return the Memiris tenant identifier for the current user.

        Returns:
            str: The tenant identifier
        """
        return ""

    def get_memiris_reference(self, dto: AutonomousTutorPipelineExecutionDTO) -> str:
        """
        Does not return any reference, as memory creation is currently disabled for this pipeline.

        Returns:
            str: "unknown"
        """
        return "unknown"

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> bool:
        """Memory creation is disabled for autonomous tutor pipeline."""
        return False

    NO_RESPONSE_MARKER = "NO_RESPONSE_NEEDED"

    def pre_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> None:
        """Log which model mode this run resolved to, before the agent starts.

        Whether a run goes to on-premise or cloud inference is decided by the
        Artemis-side selection of everyone in the thread, so it is not obvious from
        the outside which one a given post triggered. This makes it visible at a
        glance while testing.
        """
        mode = "ON-PREMISE (local)" if state.local else "CLOUD"
        selection = (
            state.dto.settings.artemis_llm_selection
            if state.dto.settings
            else "unknown"
        )
        logger.info(
            "Autonomous tutor model mode: %s | model=%s | selection=%s | course=%s | post=%s",
            mode,
            state.llm.model_name if state.llm else "unknown",
            selection,
            state.dto.course.id if state.dto.course else "unknown",
            state.dto.post.id if state.dto.post else "unknown",
        )

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> str:
        """Send the final response back to Artemis with confidence score."""
        if state.result and self.NO_RESPONSE_MARKER in state.result:
            logger.info("Post does not require a tutoring response, skipping.")
            state.callback.finish(
                result=None,
                tokens=self.tokens,
                confidence=0.0,
            )
            return ""

        confidence = self._estimate_confidence(state)
        confidence = self._cap_unsupported_organizational_confidence(state, confidence)
        state.result = self._strip_author_label(state.result)

        logger.info("Generated response: %s", state.result)
        logger.info("Confidence score | score=%.4f", confidence)

        state.callback.finish(
            result=state.result,
            tokens=self.tokens,
            confidence=confidence,
        )
        return state.result

    def _cap_unsupported_organizational_confidence(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
        confidence: float,
    ) -> float:
        """Hold back an organizational answer that no tool could support.

        Exam scope, dates, rooms, deadlines, grading and registration are facts about
        this one course. They cannot be derived from what the course teaches, so an
        answer to such a question is only worth publishing when a course FAQ entry or
        a tutor-verified prior answer actually stated it. A community-resolved prior
        answer is not that: it is a hint the agent may weigh, not evidence that lets
        the answer skip tutor review.

        Neither confidence strategy catches this on its own. The verbalized prompt
        asks the model to score itself low and it often does not; the logprob
        strategies measure how sure the model is of its own *wording*, and an invented
        exam scope is worded very fluently — it scores high. So the check is made
        here, on facts the pipeline knows: what was asked, and what the tools returned.

        The score is only ever lowered, and only to the review band, so the reply
        reaches a tutor instead of a student. See
        ``iris.pipeline.shared.organizational_guard`` for why the two sources are the
        only ones that count as support.
        """
        guard = settings.autonomous_tutor.organizational_evidence_guard
        if not guard.enabled:
            return confidence

        _, target_message = self._target_message(state.dto.post)
        category = classify_organizational_question(target_message)
        if category is None:
            return confidence

        faq_hits = getattr(state, "faq_storage", {}).get("faqs")
        memory_hits = getattr(state, "memory_storage", {}).get("memories")
        if has_organizational_evidence(faq_hits, memory_hits):
            logger.info(
                "Organizational question (%s) is supported by retrieved evidence | "
                "faqs=%d verified_memories=%d",
                category,
                len(faq_hits or []),
                len(tutor_verified_memory_hits(memory_hits)),
            )
            return confidence

        if confidence <= guard.confidence_cap:
            return confidence

        # The memory count is logged so a capped answer can be told apart from one
        # with no memory hit at all: community-resolved hits are present but do not
        # count as support.
        logger.info(
            "Capping confidence for unsupported organizational question | "
            "category=%s confidence=%.4f cap=%.4f unverified_memories=%d",
            category,
            confidence,
            guard.confidence_cap,
            len(memory_hits or []),
        )
        return guard.confidence_cap

    def _strip_author_label(self, result: str) -> str:
        """Drop a role label the model copied from the thread onto its own answer.

        The thread reaches the model with each other participant's message prefixed
        by their role, and models sometimes reproduce that prefix in the reply they
        write. Only the exact known labels are removed, so an answer that genuinely
        opens with a markdown link (``[Title](url)``) is left alone.
        """
        if not result:
            return result
        stripped = result.lstrip()
        for label in AUTHOR_ROLE_LABELS.values():
            prefix = f"[{label}]"
            if stripped.startswith(prefix):
                logger.info("Stripped author label %s from the response.", prefix)
                return stripped[len(prefix) :].lstrip()  # noqa: E203
        return result

    def _estimate_confidence(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> float:
        """Estimate the confidence score for the generated response.

        Three strategies, in order of preference:
        1. Uncertainty scoring (Xu et al., FSE '25) over the final answer's
           top-k token logprobs, when the backend returned alternatives.
        2. Mean-logprob (thesis §6.6 baseline), when only plain logprobs are
           available.
        3. Verbalized confidence parsed from the response (mutates
           ``state.result`` to drop the trailing Probability line), when the
           model does not expose logprobs at all.
        In logprob modes ``state.result`` is left untouched.

        Confidence thresholds (applied by Artemis):
        - >= 0.85: Post immediately
        - 0.70 - 0.85: Forward to verification queue
        - < 0.70: Discard

        Returns:
            float: Confidence score between 0.0 and 1.0
        """
        if getattr(state, "use_logprob_confidence", False):
            entries = getattr(state.llm, "last_token_logprob_entries", None)
            confidence = uncertainty_confidence(entries)
            if confidence is not None:
                logger.info(
                    "Confidence strategy: logprob uncertainty scoring | "
                    "confidence=%.4f",
                    confidence,
                )
                return confidence
            token_logprobs = getattr(state.llm, "last_token_logprobs", None)
            if token_logprobs is None:
                # Misconfiguration breadcrumb: the model was selected for
                # logprob mode but returned no logprobs at all. Every
                # response will score 0.0 (discard) until the model's
                # supports_logprobs flag in llm_config.yml is corrected.
                logger.warning(
                    "Model %s is configured with supports_logprobs but "
                    "returned no token logprobs; confidence defaults to 0.0 "
                    "and Artemis will discard this response.",
                    state.llm.model_name if state.llm else "<unknown>",
                )
            confidence = logprob_confidence(token_logprobs)
            logger.info(
                "Confidence strategy: mean-logprob fallback | confidence=%.4f",
                confidence,
            )
            return confidence

        answer_text, confidence = parse_confidence_response(state.result)
        state.result = answer_text
        logger.info("Confidence strategy: verbalized | confidence=%.4f", confidence)
        return confidence

    def get_recent_history_from_dto(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
        limit: int | None = None,
    ) -> list[PyrisMessage]:
        """Represent the thread as chat history, oldest message first.

        The base implementation reads ``dto.chat_history``, which this pipeline does
        not have: its input is a communication-channel thread, not a chat session.
        Turning the thread into history is what makes the newest message the one the
        agent answers, and it gives the retrieval query rewriter the context it needs
        to resolve a follow-up ("Then what is a strategy pattern") against what came
        before it.

        Iris's own earlier replies become assistant turns so it does not repeat them;
        everyone else's become user turns, prefixed with their role.

        Only the other participants' turns carry a role prefix. Iris's own turns are
        already identified by the assistant role, and prefixing them too made the
        model read "[Iris (you)] " as part of how its replies are written and copy it
        into the answer it posted.
        """
        effective_limit = limit if limit is not None else self.get_history_limit(state)
        # ``history[-0:]`` is the whole list, so a zero limit would send the entire
        # thread instead of none of it.
        if effective_limit <= 0:
            return []
        history = [
            PyrisMessage(
                sender=(
                    IrisMessageRole.ASSISTANT
                    if role == IRIS_AUTHOR_ROLE
                    else IrisMessageRole.USER
                ),
                contents=[
                    TextMessageContentDTO(
                        textContent=(
                            text if role == IRIS_AUTHOR_ROLE else f"[{label}] {text}"
                        )
                    )
                ],
            )
            for role, label, text in self._thread_turns(state.dto.post)
        ]
        return history[-effective_limit:] if history else []

    def _thread_turns(self, post: PostDTO) -> List[Tuple[str, str, str]]:
        """Flatten a thread into ``(author_role, author_label, text)`` turns, oldest first.

        Redacted messages are kept as placeholders: Iris should know a message exists
        in the thread without seeing content its author opted out of sharing.
        """
        if not post:
            return []

        turns: List[Tuple[str, str, str]] = []

        def add(role: str | None, redacted: bool, content: str | None) -> None:
            text = REDACTED_ANSWER_PLACEHOLDER if redacted else (content or "")
            if not text:
                return
            # Case-insensitive: the course-memory ingestion webhook spells the same
            # roles in lower case, so accept either spelling rather than silently
            # falling back to the neutral label.
            role = (role or "").strip().upper()
            turns.append(
                (role, AUTHOR_ROLE_LABELS.get(role, UNKNOWN_AUTHOR_LABEL), text)
            )

        add(post.author_role, False, post.content)
        for answer in post.answers or []:
            add(answer.author_role, answer.redacted, answer.content)
        return turns

    def _target_message(self, post: PostDTO) -> Tuple[str, str]:
        """Return ``(author_label, content)`` of the message Iris has to respond to.

        Artemis re-runs this pipeline on every new message in a thread and sends the
        whole thread, ordered oldest first — so the message that triggered the run is
        the newest one, not the thread's opening post.
        """
        turns = self._thread_turns(post)
        if not turns:
            return UNKNOWN_AUTHOR_LABEL, ""
        _, label, text = turns[-1]
        return label, text

    def _generate_retrieval_query_text(self, post: PostDTO) -> str:
        """Generate query text for retrieval tools.

        Only the message being responded to is used. Querying with the whole thread
        lets the opening question dominate the embedding, which made every follow-up
        retrieve — and course memory re-serve — the answer to the first question.
        Earlier messages still reach retrieval through the chat history, which the
        query rewriter uses to make context-poor follow-ups self-contained.
        """
        _, target_content = self._target_message(post)
        return target_content or ""

    @observe(name="Autonomous Tutor Pipeline")
    def __call__(
        self,
        dto: AutonomousTutorPipelineExecutionDTO,
        variant: Variant,
        callback: AutonomousTutorCallback,
    ):
        """Run the autonomous tutor pipeline."""
        try:
            logger.info("Running autonomous tutor pipeline...")
            local = dto.settings is not None and dto.settings.is_local()
            super().__call__(dto, variant, callback, local=local)
        except Exception as e:
            logger.error(
                "An error occurred while running the autonomous tutor pipeline",
                exc_info=e,
            )
            callback.fail(
                "An error occurred while running the autonomous tutor pipeline.",
                tokens=self.tokens,
            )
