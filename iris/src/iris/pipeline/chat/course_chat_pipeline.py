import json
import logging
import os
import traceback
from datetime import datetime
from typing import Any, Callable, List, Optional, cast

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langsmith import traceable

from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)

from ...common.mastery_utils import get_mastery
from ...common.memiris_setup import get_tenant_for_user
from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain import CourseChatPipelineExecutionDTO
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.data.metrics.competency_jol_dto import CompetencyJolDTO
from ...domain.variant.course_chat_variant import CourseChatVariant
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ...tools import (
    create_tool_faq_content_retrieval,
    create_tool_get_competency_list,
    create_tool_get_course_details,
    create_tool_get_exercise_list,
    create_tool_get_exercise_problem_statement,
    create_tool_get_student_exercise_metrics,
    create_tool_lecture_content_retrieval,
)
from ...web.status.status_update import (
    CourseChatStatusCallback,
)
from ..abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import (
    datetime_to_string,
    format_custom_instructions,
)
from .interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)

logger = logging.getLogger(__name__)


class CourseChatPipeline(
    AbstractAgentPipeline[CourseChatPipelineExecutionDTO, CourseChatVariant]
):
    """
    Course chat pipeline that answers course related questions from students.
    """

    session_title_pipeline: SessionTitleGenerationPipeline
    suggestion_pipeline: InteractionSuggestionPipeline
    citation_pipeline: CitationPipeline
    lecture_retriever: Optional[LectureRetrieval]
    faq_retriever: Optional[FaqRetrieval]
    jinja_env: Environment
    system_prompt_template: Any
    event: Optional[str]

    def __init__(
        self,
        event: Optional[str] = None,
    ):
        """
        Initialize the course chat pipeline.

        Args:
            event: Optional event type
        """
        super().__init__(implementation_id="course_chat_pipeline")

        self.event = event

        # Initialize retrievers and pipelines (db will be created in abstract pipeline)
        self.lecture_retriever = None
        self.faq_retriever = None
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant="course")
        self.citation_pipeline = CitationPipeline()

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "course_chat_system_prompt.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}(event={self.event})"

    def __str__(self):
        return f"{self.__class__.__name__}(event={self.event})"

    # ========================================
    # === MUST override (abstract methods) ===
    # ========================================

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Returns:
            bool: True if memory creation is enabled
        """
        return bool(state.dto.user and state.dto.user.memiris_enabled)

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
    ) -> list[Callable]:
        """
        Get the tools available for the agent pipeline.

        Returns:
            list[Callable]: A list of tools available for the agent pipeline
        """
        # Get tool permissions
        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)
        allow_faq_tool = should_allow_faq_tool(state.db, state.dto.course.id)
        allow_memiris_tool = bool(
            state.dto.user
            and state.dto.user.memiris_enabled
            and state.memiris_wrapper
            and state.memiris_wrapper.has_memories()
        )

        # Get user query text
        query_text = self.get_text_of_latest_user_message(state)

        # Create storage for shared data - using setattr to avoid mypy issues
        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})
        if not hasattr(state, "accessed_memory_storage"):
            setattr(state, "accessed_memory_storage", [])

        # Use the callback from state - cast to the correct type
        callback = state.callback
        if not isinstance(callback, CourseChatStatusCallback):
            # If it's not the right type, we need to handle this gracefully
            # For now, we'll use the base callback and cast it
            callback = cast(CourseChatStatusCallback, state.callback)

        tool_list: list[Callable] = [
            create_tool_get_course_details(state.dto.course, callback),
        ]

        if state.dto.course.exercises:
            tool_list.append(
                create_tool_get_exercise_list(state.dto.course.exercises, callback)
            )
            tool_list.append(
                create_tool_get_exercise_problem_statement(
                    state.dto.course.exercises, callback
                )
            )

        if (
            state.dto.metrics
            and state.dto.metrics.exercise_metrics
            and state.dto.course.exercises
        ):
            tool_list.append(
                create_tool_get_student_exercise_metrics(state.dto.metrics, callback)
            )

        if state.dto.course.competencies and len(state.dto.course.competencies) > 0:
            tool_list.append(
                create_tool_get_competency_list(
                    state.dto.course.competencies, state.dto.metrics, callback
                )
            )

        if allow_lecture_tool:
            self.lecture_retriever = LectureRetrieval(state.db.client)
            tool_list.append(
                create_tool_lecture_content_retrieval(
                    self.lecture_retriever,
                    state.dto.course.id,
                    state.dto.settings.artemis_base_url if state.dto.settings else "",
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
                    state.dto.settings.artemis_base_url if state.dto.settings else "",
                    callback,
                    query_text,
                    state.message_history,
                    getattr(state, "faq_storage", {}),
                )
            )

        if allow_memiris_tool and state.memiris_wrapper:
            tool_list.append(
                state.memiris_wrapper.create_tool_memory_search(
                    getattr(state, "accessed_memory_storage", [])
                )
            )
            tool_list.append(
                state.memiris_wrapper.create_tool_find_similar_memories(
                    getattr(state, "accessed_memory_storage", [])
                )
            )

        return tool_list

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
    ) -> str:
        """
        Return a system message for the chat prompt.

        Returns:
            str: The system message content
        """
        # Get tool permissions
        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)
        allow_faq_tool = should_allow_faq_tool(state.db, state.dto.course.id)
        allow_memiris_tool = bool(
            state.dto.user
            and state.dto.user.memiris_enabled
            and state.memiris_wrapper
            and state.memiris_wrapper.has_memories()
        )

        # Format custom instructions
        custom_instructions_formatted = format_custom_instructions(
            state.dto.custom_instructions or ""
        )

        # Determine metrics availability
        metrics_enabled = (
            state.dto.metrics
            and state.dto.course.competencies
            and state.dto.course.student_analytics_dashboard_enabled
        )

        # Prepare template context
        template_context = {
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "has_competencies": bool(state.dto.course.competencies),
            "has_exercises": bool(state.dto.course.exercises),
            "allow_lecture_tool": allow_lecture_tool,
            "allow_faq_tool": allow_faq_tool,
            "allow_memiris_tool": allow_memiris_tool,
            "metrics_enabled": metrics_enabled,
            "has_chat_history": bool(state.message_history),
            "event": self.event,
            "custom_instructions": custom_instructions_formatted,
            "course_name": (
                state.dto.course.name
                if state.dto.course and state.dto.course.name
                else "the course"
            ),
        }

        # Handle JOL event specific data
        if self.event == "jol" and state.dto.event_payload:
            event_payload = CompetencyJolDTO.model_validate(
                state.dto.event_payload.event
            )
            comp = next(
                (
                    c
                    for c in state.dto.course.competencies
                    if c.id == event_payload.competency_id
                ),
                None,
            )

            # Handle potential None values for competency progress and confidence
            competency_progress = event_payload.competency_progress or 0.0
            competency_confidence = event_payload.competency_confidence or 0.0

            template_context["jol"] = json.dumps(
                {
                    "value": event_payload.jol_value,
                    "competency_mastery": get_mastery(
                        competency_progress,
                        competency_confidence,
                    ),
                }
            )
            template_context["competency"] = comp.model_dump_json() if comp else "{}"

        # Render the complete system prompt
        complete_system_prompt = self.system_prompt_template.render(template_context)

        return complete_system_prompt

    def get_agent_params(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
    ) -> dict[str, Any]:
        """
        Return the parameter dict passed to the agent executor.

        Returns:
            dict[str, Any]: Parameters for the agent executor
        """
        return {}

    def get_memiris_tenant(self, dto: CourseChatPipelineExecutionDTO) -> str:
        """
        Return the Memiris tenant identifier for the current user.

        Returns:
            str: The tenant identifier
        """
        if not dto.user:
            raise ValueError("User is required for memiris tenant")
        return get_tenant_for_user(dto.user.id)

    def get_memiris_reference(self, dto: CourseChatPipelineExecutionDTO):
        """
        Return the reference to use for the Memiris learnings created in a course chat.
        It is simply the id of last user message in the chat history with a prefix.

        Returns:
            str: The reference identifier
        """
        last_message: Optional[PyrisMessage] = next(
            (
                m
                for m in reversed(dto.conversation or [])
                if m.sender == IrisMessageRole.USER
            ),
            None,
        )
        return (
            f"session-messages/{last_message.id}"
            if last_message and last_message.id
            else "session-messages/unknown"
        )

    # ========================================
    # === CAN override (optional methods) ===
    # ========================================

    def on_agent_step(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
        step: dict[str, Any],
    ) -> None:
        """
        Handle each agent execution step.

        Args:
            state: The current pipeline execution state.
            step: The current step information.
        """
        # Update progress
        if step.get("intermediate_steps"):
            state.callback.in_progress("Thinking ...")

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
    ) -> str:
        """
        Post-processing after agent execution including citations and suggestions.

        Returns:
            str: The final result
        """
        # Process citations if we have them
        if hasattr(state, "lecture_content_storage") and hasattr(state, "faq_storage"):
            state.result = self._process_citations(
                state,
                state.result,
                state.lecture_content_storage,
                state.faq_storage,
                state.dto,
                state.variant,
            )

        # Generate title
        session_title = self._generate_session_title(state, state.result, state.dto)

        # Generate suggestions
        suggestions = self._generate_suggestions(state, state.result, state.dto)

        state.callback.done(
            "Response created",
            final_result=state.result,
            tokens=state.tokens,
            accessed_memories=getattr(state, "accessed_memory_storage", []),
            suggestions=suggestions,
            session_title=session_title,
        )

        return state.result

    # ========================================
    # === Private helper methods ===
    # ========================================

    def _process_citations(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
        output: str,
        lecture_content_storage: dict[str, Any],
        faq_storage: dict[str, Any],
        dto: CourseChatPipelineExecutionDTO,
        variant: CourseChatVariant,
    ) -> str:
        """
        Process citations for lecture content and FAQs.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            lecture_content_storage: Storage for lecture content
            faq_storage: Storage for FAQ content
            dto: The pipeline execution DTO
            variant: The variant configuration

        Returns:
            str: The output with citations added
        """
        if lecture_content_storage.get("content"):
            base_url = dto.settings.artemis_base_url if dto.settings else ""
            output = self.citation_pipeline(
                lecture_content_storage["content"],
                output,
                InformationType.PARAGRAPHS,
                variant=variant.id,
                base_url=base_url,
            )
        if hasattr(self.citation_pipeline, "tokens") and self.citation_pipeline.tokens:
            for token in self.citation_pipeline.tokens:
                self._track_tokens(state, token)

        if faq_storage.get("faqs"):
            base_url = dto.settings.artemis_base_url if dto.settings else ""
            output = self.citation_pipeline(
                faq_storage["faqs"],
                output,
                InformationType.FAQS,
                variant=variant.id,
                base_url=base_url,
            )

        return output

    def _generate_suggestions(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
        output: str,
        dto: CourseChatPipelineExecutionDTO,
    ) -> Optional[Any]:
        """
        Generate interaction suggestions based on the output.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            dto: The pipeline execution DTO

        Returns:
            The generated suggestions or None if generation failed
        """
        try:
            if output:
                suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                suggestion_dto.chat_history = dto.chat_history
                suggestion_dto.last_message = output
                suggestions = self.suggestion_pipeline(suggestion_dto)

                if self.suggestion_pipeline.tokens is not None:
                    self._track_tokens(state, self.suggestion_pipeline.tokens)

                return suggestions
            else:
                # This should never happen but whatever
                logger.warning("No output generated, skipping suggestion generation")
                return None
        except Exception as e:
            logger.error(
                "An error occurred while running the course chat interaction suggestion pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            return None

    def _generate_session_title(
        self,
        state: AgentPipelineExecutionState[
            CourseChatPipelineExecutionDTO, CourseChatVariant
        ],
        output: str,
        dto: CourseChatPipelineExecutionDTO,
    ) -> Optional[str]:
        """
        Generate session title from the first user prompt and the model output.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            dto: The pipeline execution DTO

        Returns:
            The generated session title or None if not applicable
        """
        # Generate only the 'first time'
        # - course chat may start with an Iris greeting (len == 2 once the user sends the first msg)
        # - or directly with the user's first message (len == 1)
        if len(dto.chat_history) in (1, 2):
            first_user_msg = (
                dto.chat_history[len(dto.chat_history) - 1].contents[0].text_content
            )
            return super()._create_session_title(state, output, first_user_msg)
        return None

    @traceable(name="Course Chat Pipeline")
    def __call__(
        self,
        dto: CourseChatPipelineExecutionDTO,
        variant: CourseChatVariant,
        callback: CourseChatStatusCallback,
    ):
        """
        Run the course chat pipeline.

        Args:
            dto: The pipeline execution data transfer object
            variant: The variant configuration
            callback: The status callback
        """
        try:
            logger.info("Running course chat pipeline...")

            # Call the parent __call__ method which handles the complete execution
            super().__call__(dto, variant, callback)

        except Exception as e:
            logger.error(
                "An error occurred while running the course chat pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            callback.error(
                "An error occurred while running the course chat pipeline.",
                tokens=[],
            )

    @classmethod
    def get_variants(cls) -> List[CourseChatVariant]:  # type: ignore[override]
        """
        Get available variants for the course chat pipeline.

        Returns:
            List[CourseChatVariant]: List of available variants
        """
        return [
            CourseChatVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini",
                citation_model="gpt-4.1-mini",
            ),
            CourseChatVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1",
                citation_model="gpt-4.1-mini",
            ),
        ]
