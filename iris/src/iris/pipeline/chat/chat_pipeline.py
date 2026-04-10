import os
from datetime import datetime
from typing import Any, Callable, Optional

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from iris.common.logging_config import get_logger
from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.pipeline.chat.iris_chat_mode import IrisChatMode
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)
from iris.tools.chat_tool_providers import CHAT_TOOL_PROVIDERS
from iris.tracing import observe
from iris.web.status.status_update import StatusCallback

from ...common.memiris_setup import get_tenant_for_user
from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.variant.variant import Dep, Variant
from ...llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.mcq_generation_pipeline import McqGenerationPipeline
from ..shared.utils import datetime_to_string, format_custom_instructions
from .code_feedback_pipeline import CodeFeedbackPipeline
from .interaction_suggestion_pipeline import InteractionSuggestionPipeline
from .mcq_chat_mixin import (
    detect_mcq_intent,
    mcq_execute_agent,
    mcq_post_agent_hook,
    mcq_pre_agent_hook,
)

logger = get_logger(__name__)

_SUGGESTION_VARIANT: dict[IrisChatMode, str] = {
    IrisChatMode.COURSE: "course",
    IrisChatMode.EXERCISE: "exercise",
}


class ChatPipeline(AbstractAgentPipeline[ChatPipelineExecutionDTO, Variant]):
    """
    Replaces CourseChatPipeline / ExerciseChatPipeline / TextExerciseChatPipeline / LectureChatPipeline
    """

    # TODO: REFACTORING ASLAN: ÜBERARBEITEN
    PIPELINE_ID = "chat_pipeline"
    ROLES = {"chat"}
    VARIANT_DEFS = [
        ("default", "Default", "Uses a smaller model for faster responses."),
        ("advanced", "Advanced", "Uses a larger model, balancing speed and quality."),
    ]
    DEPENDENCIES = [
        Dep("citation_pipeline", variant="same"),
        Dep("session_title_generation_pipeline"),
        Dep("interaction_suggestion_pipeline", variant="course"),
        Dep("interaction_suggestion_pipeline", variant="exercise"),
        Dep("code_feedback_pipeline"),
        Dep("mcq_generation_pipeline"),
        Dep("lecture_retrieval_pipeline"),
        Dep("lecture_unit_segment_retrieval_pipeline"),
        Dep("lecture_transcriptions_retrieval_pipeline"),
        Dep("faq_retrieval_pipeline"),
    ]

    chat_mode: IrisChatMode
    event: Optional[str]
    session_title_pipeline: SessionTitleGenerationPipeline
    citation_pipeline: CitationPipeline
    suggestion_pipeline: Optional[InteractionSuggestionPipeline]
    code_feedback_pipeline: Optional[CodeFeedbackPipeline]
    mcq_pipeline: McqGenerationPipeline
    jinja_env: Environment
    system_prompt_template: Any
    guide_prompt_template: Any

    def __init__(self, chat_mode: IrisChatMode, local: bool = False):
        """
        Initialize the exercise chat agent pipeline.
        """
        super().__init__(implementation_id=self.PIPELINE_ID)

        self.chat_mode = chat_mode

        self.event = None

        # Initialize pipelines & retrievers
        self.session_title_pipeline = SessionTitleGenerationPipeline(local=local)
        self.citation_pipeline = CitationPipeline(local=local)
        suggestion_variant = _SUGGESTION_VARIANT.get(self.chat_mode, "course")
        self.suggestion_pipeline = InteractionSuggestionPipeline(
            variant=suggestion_variant, local=local
        )
        self.code_feedback_pipeline = CodeFeedbackPipeline(
            local=local
        )  # TODO: Ungenutzt? Entfernen?
        self.mcq_pipeline = McqGenerationPipeline(local=local)

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        # Setup system prompt
        self.system_prompt_template = self.jinja_env.get_template(
            "chat_system_prompt.j2"
        )
        self.guide_prompt_template = self.jinja_env.get_template(
            "exercise_chat_guide_prompt.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}(context={self.chat_mode.value})"

    def __str__(self):
        return f"{self.__class__.__name__}(context={self.chat_mode.value})"

    def get_memiris_reference(self, dto: ChatPipelineExecutionDTO):
        """
        Return the reference to use for the Memiris learnings created in a programming exercise chat.
        It is simply the id of last user message in the chat history with a prefix.

        Returns:
            str: The reference identifier
        """
        last_message: Optional[PyrisMessage] = next(
            (
                m
                for m in reversed(dto.chat_history or [])
                if m.sender == IrisMessageRole.USER
            ),
            None,
        )
        return (
            f"session-messages/{last_message.id}"
            if last_message and last_message.id
            else "session-messages/unknown"
        )

    def get_memiris_tenant(self, dto: ChatPipelineExecutionDTO) -> str:
        """
        Return the Memiris tenant identifier for the current user.

        Args:
            dto: The execution DTO containing user information.

        Returns:
            The tenant identifier string.
        """
        if not dto.user:
            raise ValueError("User is required for memiris tenant")
        return get_tenant_for_user(dto.user.id)

    def on_agent_step(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
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

    def pre_agent_hook(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> None:
        """Spawn parallel MCQ generation thread if intent was detected."""
        if self.chat_mode not in {IrisChatMode.COURSE, IrisChatMode.LECTURE}:
            return
        lecture_id = (
            state.dto.lecture.id if state.dto.lecture and state.dto.lecture.id else None
        )
        course_id = state.dto.course.id if state.dto.course else None
        if course_id is None:
            return
        mcq_pre_agent_hook(
            state=state,
            mcq_pipeline=self.mcq_pipeline,
            get_text_of_latest_user_message=self.get_text_of_latest_user_message,
            db=state.db,
            course_id=course_id,
            chat_history=state.dto.chat_history,
            lecture_id=lecture_id,
        )

    def execute_agent(self, state):
        """Use a direct LLM call when MCQ parallel is active, else default agent."""
        if getattr(state, "mcq_parallel", False):
            return mcq_execute_agent(state)
        return super().execute_agent(state)

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> str:
        """
        Process results after agent execution.

        Args:
            state: The current pipeline execution state.

        Returns:
            The processed result string.
        """
        try:
            # Handle MCQ placeholder replacement and parallel thread joining
            mcq_post_agent_hook(
                state=state,
                mcq_pipeline=self.mcq_pipeline,
                track_tokens=self._track_tokens,
            )

            result = state.result

            # If Programming Exercise, refine response using guide prompt
            if self.chat_mode == IrisChatMode.EXERCISE:
                result = self._refine_response(state)

            # Add citations if applicable
            result = self._add_citations(state, result)

            # Generate title
            session_title = self._generate_session_title(state, result, state.dto)

            # Send the result first so the user sees the message immediately
            state.callback.done(
                "Response created",
                final_result=result,
                tokens=state.tokens,
                session_title=session_title,
                accessed_memories=state.accessed_memory_storage,
            )

            # Generate and send suggestions separately (async from user's perspective)
            if self.chat_mode in [
                IrisChatMode.COURSE,
                IrisChatMode.EXERCISE,
            ]:  # TODO: Suggestions: Text_Exercise? Lecture?
                self._generate_suggestions(state, result)

            return result

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            state.callback.error("Error in processing response")
            return state.result

    def prepare_state(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> None:
        """
        Pre-compute tool availability flags once, so both build_system_message
        and get_tools can read them without redundant DB calls.
        Also detects MCQ intent for COURSE and LECTURE modes.
        """
        dto = state.dto
        course_id = dto.course.id if dto.course else None
        state.allow_lecture_tool = should_allow_lecture_tool(state.db, course_id)
        state.allow_faq_tool = should_allow_faq_tool(state.db, course_id)
        state.allow_memiris_tool = bool(
            dto.user
            and dto.user.memiris_enabled
            and state.memiris_wrapper
            and state.memiris_wrapper.has_memories()
        )
        state.query_text = self.get_text_of_latest_user_message(state)

        # Detect MCQ intent for modes that support it
        if self.chat_mode in {IrisChatMode.COURSE, IrisChatMode.LECTURE}:
            is_mcq, count = detect_mcq_intent(state.query_text)
            if is_mcq:
                state.mcq_parallel = True
                state.mcq_count = count

    def get_tools(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> list[Callable]:
        """
        Create and return tools for the agent.

        Iterates over all registered tool providers and collects the ones
        whose required data is present in the current state.

        When MCQ parallel mode is active the agent only needs to write a
        short intro — no tools required.

        Args:
            state: The current pipeline execution state.

        Returns:
            List of tool functions for the agent.
        """
        if getattr(state, "mcq_parallel", False):
            return []

        tools: list[Callable] = []
        for provider in CHAT_TOOL_PROVIDERS:
            tool = provider(state)
            if tool is not None:
                tools.append(tool)
        return tools

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> str:
        """
        Build the system message/prompt for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            The system prompt string.
        """
        dto = state.dto

        # Extract user language
        user_language = "en"
        if dto.user and dto.user.lang_key:
            user_language = dto.user.lang_key

        # Custom instructions
        custom_instructions = format_custom_instructions(dto.custom_instructions or "")

        course_name = ""
        if dto.course and dto.course.name:
            course_name = dto.course.name
        elif dto.exercise and dto.exercise.course:
            course_name = dto.exercise.course.name

        metrics_enabled = bool(
            dto.metrics
            and dto.course
            and dto.course.competencies
            and dto.course.student_analytics_dashboard_enabled
        )

        query = self.get_latest_user_message(state)

        # Base template context (shared across all contexts)
        template_context: dict[str, Any] = {
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "user_language": user_language,
            "custom_instructions": custom_instructions,
            "course_name": course_name,
            "allow_lecture_tool": state.allow_lecture_tool,
            "allow_faq_tool": state.allow_faq_tool,
            "allow_memiris_tool": state.allow_memiris_tool,
            "metrics_enabled": metrics_enabled,
            "has_chat_history": bool(state.message_history),
            "has_competencies": bool(dto.course and dto.course.competencies),
            "has_exercises": bool(dto.course and dto.course.exercises),
            "has_query": query is not None,
            "lecture_name": dto.lecture.title if dto.lecture else None,
            "exercise_title": (dto.exercise.name if dto.exercise else ""),
            "problem_statement": (
                dto.exercise.problem_statement if dto.exercise else ""
            ),
            "programming_language": (
                dto.exercise.programming_language.lower()
                if dto.exercise
                and hasattr(dto.exercise, "programming_language")
                and dto.exercise.programming_language
                else ""
            ),
            "exercise_id": (dto.exercise.id if dto.exercise else ""),
            "start_date": (
                str(dto.exercise.start_date)
                if dto.exercise and dto.exercise.start_date
                else ""
            ),
            "end_date": (
                str(dto.exercise.end_date)
                if dto.exercise and dto.exercise.end_date
                else ""
            ),
            "text_exercise_submission": dto.text_exercise_submission,
            "mcq_parallel": getattr(state, "mcq_parallel", False),
        }

        return self.system_prompt_template.render(template_context)

    def is_memiris_memory_creation_enabled(
        self, state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant]
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Args:
            state: The current pipeline execution state.

        Returns:
            True if memory creation should be enabled, False otherwise.
        """
        if self.chat_mode in {IrisChatMode.COURSE, IrisChatMode.LECTURE}:
            return bool(state.dto.user and state.dto.user.memiris_enabled)
        else:
            return False

    def _add_citations(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        result: str,
    ) -> str:
        """
        Add citations to the response if applicable.

        Args:
            state: The current pipeline execution state.
            result: The current result string.

        Returns:
            The result with citations added.
        """
        # Extract user language
        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        try:
            # Add FAQ citations
            if state.faq_storage.get("faqs"):
                state.callback.in_progress("Adding FAQ references...")
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    state.faq_storage["faqs"],
                    result,
                    InformationType.FAQS,
                    variant=state.variant.id,
                    user_language=user_language,
                    base_url=base_url,
                )

            # Add lecture content citations
            if state.lecture_content_storage.get("content"):
                state.callback.in_progress("Adding lecture references...")
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    state.lecture_content_storage["content"],
                    result,
                    InformationType.PARAGRAPHS,
                    variant=state.variant.id,
                    user_language=user_language,
                    base_url=base_url,
                )

            # Track tokens from citation pipeline
            if (
                hasattr(self.citation_pipeline, "tokens")
                and self.citation_pipeline.tokens
            ):
                for token in self.citation_pipeline.tokens:
                    self._track_tokens(state, token)

            return result

        except Exception as e:
            logger.error("Error adding citations", exc_info=e)
            return result

    def _generate_session_title(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        output: str,
        dto: ChatPipelineExecutionDTO,
    ) -> Optional[str]:
        """
        Generate a session title from the latest user prompt and the model output.

        Args:
            state: The current pipeline execution state
            output: The agent's output
            dto: The pipeline execution DTO

        Returns:
            The generated session title or None if not applicable
        """
        return self.update_session_title(state, output, dto.session_title)

    @observe(name="Response Refinement")
    def _refine_response(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
    ) -> str:
        """
        Refine the agent response using the guide prompt. This is only available for programming exercises.

        Args:
            state: The current pipeline execution state.

        Returns:
            The refined response.
        """
        try:
            # Don't do anything if not programming exercise
            if self.chat_mode is not IrisChatMode.EXERCISE:
                return state.result

            state.callback.in_progress("Refining response ...")

            problem_statement = (
                state.dto.exercise.problem_statement if state.dto.exercise else ""
            )
            guide_prompt_rendered = self.guide_prompt_template.render(
                {"problem_statement": problem_statement}
            )

            # Create small LLM for refinement
            completion_args = CompletionArguments(temperature=0.5, max_tokens=2000)
            refinement_model = state.variant.model("chat", state.local)
            llm_small = IrisLangchainChatModel(
                request_handler=LlmRequestHandler(model_id=refinement_model),
                completion_args=completion_args,
            )

            prompt = ChatPromptTemplate.from_messages(
                [
                    SystemMessage(content=guide_prompt_rendered),
                    HumanMessage(content=state.result),
                ]
            )

            guide_response = (prompt | llm_small | StrOutputParser()).invoke({})

            self._track_tokens(state, llm_small.tokens)

            if "!ok!" in guide_response:
                logger.info("Response is ok and not rewritten")
                return state.result
            else:
                logger.info("Response is rewritten")
                return guide_response

        except Exception as e:
            logger.error("Error in refining response", exc_info=e)
            state.callback.error("Error in refining response")
            return state.result

    def _generate_suggestions(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, Variant],
        result: str,
    ) -> None:
        """
        Generate interaction suggestions. This is only available IrisChatMode.COURSE, IrisChatMode.EXERCISE.

        Args:
            state: The current pipeline execution state.
            result: The final result string.
        """
        if self.chat_mode not in {IrisChatMode.COURSE, IrisChatMode.EXERCISE}:
            return

        # Extract user language
        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        try:
            if result:
                suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                suggestion_dto.chat_history = state.dto.chat_history
                suggestion_dto.last_message = result
                suggestions = self.suggestion_pipeline(
                    suggestion_dto, user_language=user_language
                )

                if self.suggestion_pipeline.tokens is not None:
                    self._track_tokens(state, self.suggestion_pipeline.tokens)

                state.callback.done(
                    final_result=None,
                    suggestions=suggestions,
                    tokens=state.tokens,
                )
            else:
                state.callback.skip(
                    "Skipping suggestion generation as no output was generated."
                )

        except Exception as e:
            logger.error("Error generating suggestions", exc_info=e)
            state.callback.error("Generating interaction suggestions failed.")

    @observe(name="Chat Pipeline")
    def __call__(
        self,
        dto: ChatPipelineExecutionDTO,
        variant: Variant,
        callback: StatusCallback,
        event: str | None = None,
    ):
        """
        Execute the pipeline with the provided arguments.

        Args:
            dto: Execution data transfer object.
            variant: The variant configuration to use.
            callback: Status callback for progress updates.
            event: Optional event identifier (e.g. "jol").
        """
        try:
            logger.info("Running chat pipeline...")

            self.event = event

            # Delegate to parent class for standardized execution
            local = dto.settings is not None and dto.settings.is_local()
            super().__call__(dto, variant, callback, local=local)

        except Exception as e:
            logger.error(
                "An error occurred while running the chat pipeline.", exc_info=e
            )
            callback.error("An error occurred while running the chat pipeline.")
