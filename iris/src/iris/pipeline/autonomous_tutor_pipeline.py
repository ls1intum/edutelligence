import os
from typing import Callable, List, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from iris.common.logging_config import get_logger
from iris.domain.autonomous_tutor.autonomous_tutor_pipeline_execution_dto import (
    AutonomousTutorPipelineExecutionDTO,
)
from iris.domain.variant.autonomous_tutor_variant import AutonomousTutorVariant
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.pipeline.shared.utils import (
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
    AbstractAgentPipeline[AutonomousTutorPipelineExecutionDTO, AutonomousTutorVariant]
):
    """
    The AutonomousTutorPipeline autonomously responds to student posts.
    It analyzes the post and generates a helpful response based on available context.
    """

    DIRECT_POST_CONFIDENCE_THRESHOLD = 0.95

    def __init__(self):
        super().__init__(implementation_id="autonomous_tutor_pipeline")
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

        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}"

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, AutonomousTutorVariant
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
            AutonomousTutorPipelineExecutionDTO, AutonomousTutorVariant
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
        return self.system_prompt_template.render(template_context)

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
            AutonomousTutorPipelineExecutionDTO, AutonomousTutorVariant
        ],
    ) -> bool:
        """Memory creation is disabled for autonomous tutor pipeline."""
        return False

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            AutonomousTutorPipelineExecutionDTO, AutonomousTutorVariant
        ],
    ) -> str:
        """Send the final response back to Artemis with confidence score."""
        # TODO(IRIS-22): Implement Confidence Evaluation
        # For now, use a placeholder confidence value
        confidence = self._estimate_confidence(state)
        should_post_directly = confidence >= self.DIRECT_POST_CONFIDENCE_THRESHOLD

        logger.info("Generated response: %s", state.result)

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
        state: AgentPipelineExecutionState[  # pylint: disable=unused-argument
            AutonomousTutorPipelineExecutionDTO, AutonomousTutorVariant
        ],
    ) -> float:
        """
        Estimate confidence score for the generated response.

        Confidence thresholds:
        - >= 0.95: Post immediately
        - 0.80 - 0.95: Forward to verification queue
        - < 0.80: Do not post, forward to verification queue

        TODO: Implement actual confidence estimation

        Returns:
            float: Confidence score between 0.0 and 1.0
        """
        return 0.99

    def _generate_retrieval_query_text(self, discussion: str) -> str:
        """Generate query text for retrieval tools."""
        return f"Find relevant content for the following discussion: {discussion}"

    def _format_discussion_responses(self, post) -> str:
        """Format the discussion responses (answers) from a post."""
        if not post or not post.answers:
            return ""
        responses = []
        for answer in post.answers:
            if answer.content:
                responses.append(f"- {answer.content}")
        return "\n".join(responses)

    @observe(name="Autonomous Tutor Pipeline")
    def __call__(
        self,
        dto: AutonomousTutorPipelineExecutionDTO,
        variant: AutonomousTutorVariant,
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

    @classmethod
    def get_variants(cls) -> List[AutonomousTutorVariant]:
        """Returns available variants for the AutonomousTutorPipeline."""
        return [
            AutonomousTutorVariant(
                variant_id="default",
                name="Default",
                description="Default autonomous tutor variant using the OpenAI GPT-OSS 20B model.",
                cloud_agent_model="gpt-oss:latest",
                local_agent_model="gpt-oss:latest",
            ),
        ]
