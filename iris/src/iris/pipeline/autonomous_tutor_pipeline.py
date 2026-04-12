import os
from typing import Callable, List, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from iris.common.logging_config import get_logger
from iris.domain.autonomous_tutor.autonomous_tutor_pipeline_execution_dto import (
    AutonomousTutorPipelineExecutionDTO,
)
from iris.domain.variant.variant import Dep, Variant
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.pipeline.shared.confidence_scoring import (
    is_large_model,
    parse_confidence_response,
)
from iris.pipeline.shared.utils import (
    REDACTED_ANSWER_PLACEHOLDER,
    format_post_discussion,
    get_current_utc_datetime_string,
)
from iris.retrieval.faq_retrieval import FaqRetrieval
from iris.retrieval.faq_retrieval_utils import should_allow_faq_tool
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.tools import (
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
    ]

    DIRECT_POST_CONFIDENCE_THRESHOLD = 0.95

    def __init__(self):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.lecture_retriever = None
        self.faq_retriever = None

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
        is_programming_exercise = state.dto.programming_exercise is not None
        is_text_exercise = state.dto.text_exercise is not None

        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})

        callback = state.callback
        if not isinstance(callback, AutonomousTutorCallback):
            callback = cast(AutonomousTutorCallback, state.callback)
        discussion = format_post_discussion(state.dto.post)

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

        query_text = self._generate_retrieval_query_text(discussion)

        if allow_lecture_tool:
            self.lecture_retriever = LectureRetrieval(state.db.client)
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
            self.faq_retriever = FaqRetrieval(state.db.client)
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

        tool_list.append(
            create_tool_get_simple_course_details(state.dto.course, callback)
        )

        return tool_list

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> str:
        post = state.dto.post
        has_discussion = post.answers and len(post.answers) > 0

        template_context = {
            "current_date": get_current_utc_datetime_string(),
            "allow_lecture_tool": should_allow_lecture_tool(
                state.db, state.dto.course.id
            ),
            "allow_faq_tool": should_allow_faq_tool(state.db, state.dto.course.id),
            "is_programming_exercise": state.dto.programming_exercise is not None,
            "is_text_exercise": state.dto.text_exercise is not None,
            "student_question": post.content if post else "No question provided.",
            "has_discussion": has_discussion,
            "discussion_responses": (
                self._format_discussion_responses(post) if has_discussion else ""
            ),
            "course_name": (
                state.dto.course.name
                if state.dto.course and state.dto.course.name
                else "the course"
            ),
        }
        base_prompt = self.system_prompt_template.render(template_context)
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

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> str:
        """Send the final response back to Artemis with confidence score."""
        if state.result and self.NO_RESPONSE_MARKER in state.result:
            logger.info("Post does not require a tutoring response, skipping.")
            state.callback.done(
                "No response needed",
                final_result=None,
                tokens=self.tokens,
                confidence=0.0,
                should_post_directly=False,
            )
            return ""

        confidence = self._estimate_confidence(state)
        should_post_directly = confidence >= self.DIRECT_POST_CONFIDENCE_THRESHOLD

        logger.info("Generated response: %s", state.result)
        logger.info(
            "Confidence score | score=%.4f should_post_directly=%s",
            confidence,
            should_post_directly,
        )

        state.callback.done(
            "Response generated",
            final_result=state.result,
            tokens=self.tokens,
            confidence=confidence,
            should_post_directly=should_post_directly,
        )
        return state.result

    def _estimate_confidence(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, Variant
        ],
    ) -> float:
        """Parse the verbalized confidence score from the agent's response.

        Mutates state.result to contain only the clean answer text (without the
        trailing Probability line), and returns the extracted probability.

        Confidence thresholds:
        - >= 0.95: Post immediately
        - 0.80 - 0.95: Forward to verification queue
        - < 0.80: Do not post, forward to verification queue

        Returns:
            float: Confidence score between 0.0 and 1.0
        """
        answer_text, confidence = parse_confidence_response(state.result)
        state.result = answer_text
        return confidence

    def _generate_retrieval_query_text(self, discussion: str) -> str:
        """Generate query text for retrieval tools."""
        return f"Find relevant content for the following discussion: {discussion}"

    def _format_discussion_responses(self, post) -> str:
        """Format the discussion responses (answers) from a post."""
        if not post or not post.answers:
            return ""
        responses = []
        for answer in post.answers:
            if answer.redacted:
                responses.append(f"- {REDACTED_ANSWER_PLACEHOLDER}")
            elif answer.content:
                responses.append(f"- {answer.content}")
        return "\n".join(responses)

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
            super().__call__(dto, variant, callback)
        except Exception as e:
            logger.error(
                "An error occurred while running the autonomous tutor pipeline",
                exc_info=e,
            )
            callback.error(
                "An error occurred while running the autonomous tutor pipeline.",
                tokens=self.tokens,
            )
