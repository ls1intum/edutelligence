import json
import os
from datetime import datetime
from typing import Any, Callable, List, Optional

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from iris.common.logging_config import get_logger
from iris.common.mastery_utils import get_mastery
from iris.common.memiris_setup import get_tenant_for_user
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.chat.chat_pipeline_execution_dto import ChatPipelineExecutionDTO
from iris.domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from iris.domain.data.metrics.competency_jol_dto import CompetencyJolDTO
from iris.domain.variant.chat_variant import ChatVariant
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.pipeline.chat.chat_context import ChatContext
from iris.pipeline.chat.code_feedback_pipeline import CodeFeedbackPipeline
from iris.pipeline.chat.interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)
from iris.pipeline.shared.citation_pipeline import CitationPipeline, InformationType
from iris.pipeline.shared.utils import datetime_to_string, format_custom_instructions
from iris.retrieval.faq_retrieval_utils import should_allow_faq_tool
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.tools.chat_tool_providers import (
    CHAT_TOOL_PROVIDERS,
    provide_faq_retrieval,
    provide_lecture_retrieval,
)
from iris.tracing import observe
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class ChatPipeline(AbstractAgentPipeline[ChatPipelineExecutionDTO, ChatVariant]):
    """
    Replaces CourseChatPipeline / ExerciseChatPipeline / TextExerciseChatPipeline / LectureChatPipeline
    """

    context: ChatContext
    event: Optional[str]
    session_title_pipeline: SessionTitleGenerationPipeline
    citation_pipeline: CitationPipeline
    suggestion_pipeline: Optional[InteractionSuggestionPipeline]
    code_feedback_pipeline: Optional[CodeFeedbackPipeline]
    jinja_env: Environment
    system_prompt_template: Any
    guide_prompt_template: Any

    def __init__(
        self,
        context: ChatContext,
    ):
        super().__init__(implementation_id="chat_pipeline")

        self.context = context

        self.event = None

        # Initialize pipelines & retrievers
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.citation_pipeline = CitationPipeline()
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant=self.context)
        self.code_feedback_pipeline = (
            CodeFeedbackPipeline()
        )  # TODO: Ungenutzt? Entfernen?

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        # Setup system prompt
        self.system_prompt_template = self.jinja_env.get_template(
            "chat_system_prompt2.j2"
        )
        self.guide_prompt_template = self.jinja_env.get_template(
            "exercise_chat_guide_prompt.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}(context={self.context.value})"

    def __str__(self):
        return f"{self.__class__.__name__}(context={self.context.value})"

    @classmethod
    def get_variants(cls) -> List[ChatVariant]:
        return [
            ChatVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini",
            ),
            ChatVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1",
            ),
        ]

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
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
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
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
    ) -> str:
        """
        Process results after agent execution.

        Args:
            state: The current pipeline execution state.

        Returns:
            The processed result string.
        """
        try:
            result = state.result

            # If Programming Exercise, refine response using guide prompt
            if self.context == ChatContext.EXERCISE:
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
                accessed_memories=(
                    getattr(state, "accessed_memories", [])
                    if self.context in [ChatContext.COURSE, ChatContext.LECTURE]
                    else None
                ),
            )  # TODO: Memiris: Exercise? Text Exercise?

            # Generate and send suggestions separately (async from user's perspective)
            if self.context in [
                ChatContext.COURSE,
                ChatContext.EXERCISE,
            ]:  # TODO: Suggestions: Text_Exercise? Lecture?
                self._generate_suggestions(state, result)

            return result

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            state.callback.error("Error in processing response")
            return state.result

    def get_tools(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
    ) -> list[Callable]:
        """
        Create and return tools for the agent.

        Iterates over all registered tool providers and collects the ones
        that are applicable for the current context and state.

        Args:
            state: The current pipeline execution state.

        Returns:
            List of tool functions for the agent.
        """
        # Initialize shared storage on state
        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})
        if not hasattr(state, "accessed_memory_storage"):
            setattr(state, "accessed_memory_storage", [])
        query_text = self.get_text_of_latest_user_message(state)

        tools: list[Callable] = []

        lecture_retrieval = provide_lecture_retrieval(state, query_text)
        if lecture_retrieval:
            tools.append(lecture_retrieval)

        faq_retrieval = provide_faq_retrieval(state, query_text)
        if faq_retrieval:
            tools.append(faq_retrieval)

        for provider in CHAT_TOOL_PROVIDERS:
            tool = provider(state, self.context)
            if tool is not None:
                tools.append(tool)
        return tools

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
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

        # Tool availability
        course_id = dto.course.id if dto.course else None
        allow_lecture_tool = should_allow_lecture_tool(state.db, course_id)
        allow_faq_tool = should_allow_faq_tool(state.db, course_id)
        allow_memiris_tool = bool(
            dto.user
            and dto.user.memiris_enabled
            and state.memiris_wrapper
            and state.memiris_wrapper.has_memories()
        )

        # Custom instructions
        custom_instructions = format_custom_instructions(dto.custom_instructions or "")

        # Base template context (shared across all contexts)
        template_context: dict[str, Any] = {
            "context": self.context.value,
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "user_language": user_language,
            "custom_instructions": custom_instructions,
            "has_chat_history": bool(state.message_history),
            "event": self.event,
            "course_name": (dto.course.name if dto.course and dto.course.name else ""),
            "allow_lecture_tool": allow_lecture_tool,
            "allow_faq_tool": allow_faq_tool,
            "allow_memiris_tool": allow_memiris_tool,
        }

        # Context-specific variables
        if self.context == ChatContext.COURSE:
            metrics_enabled = bool(
                dto.metrics
                and dto.course
                and dto.course.competencies
                and dto.course.student_analytics_dashboard_enabled
            )
            template_context.update(
                {
                    "has_competencies": bool(dto.course and dto.course.competencies),
                    "has_exercises": bool(dto.course and dto.course.exercises),
                    "metrics_enabled": metrics_enabled,
                }
            )
            # JoL event data
            if self.event == "jol" and dto.event_payload:
                event_payload = CompetencyJolDTO.model_validate(dto.event_payload.event)
                comp = next(
                    (
                        c
                        for c in dto.course.competencies
                        if c.id == event_payload.competency_id
                    ),
                    None,
                )
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
                template_context["competency"] = (
                    comp.model_dump_json() if comp else "{}"
                )

        elif self.context == ChatContext.LECTURE:
            template_context["lecture_name"] = (
                dto.lecture.title if dto.lecture else None
            )

        elif self.context == ChatContext.EXERCISE:
            query = self.get_latest_user_message(state)
            template_context.update(
                {
                    "exercise_title": (dto.exercise.name if dto.exercise else ""),
                    "problem_statement": (
                        dto.exercise.problem_statement if dto.exercise else ""
                    ),
                    "programming_language": (
                        dto.exercise.programming_language.lower()
                        if dto.exercise and dto.exercise.programming_language
                        else ""
                    ),
                    "has_query": query is not None,
                }
            )

        elif self.context == ChatContext.TEXT_EXERCISE:
            template_context.update(
                {
                    "exercise_id": (dto.exercise.id if dto.exercise else ""),
                    "exercise_title": (dto.exercise.title if dto.exercise else ""),
                    "course_name": (
                        dto.exercise.course.name
                        if dto.exercise and dto.exercise.course
                        else ""
                    ),
                    "problem_statement": (
                        dto.exercise.problem_statement if dto.exercise else ""
                    ),
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
                    "current_submission": dto.text_exercise_submission,
                }
            )

        return self.system_prompt_template.render(template_context)

    def is_memiris_memory_creation_enabled(
        self, state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant]
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Args:
            state: The current pipeline execution state.

        Returns:
            True if memory creation should be enabled, False otherwise.
        """
        if self.context in {ChatContext.COURSE, ChatContext.LECTURE}:
            return bool(state.dto.user and state.dto.user.memiris_enabled)
        else:
            return False

    def _add_citations(
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
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
            faq_storage = getattr(state, "faq_storage", {})
            if faq_storage.get("faqs"):
                state.callback.in_progress("Adding FAQ references...")
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    faq_storage["faqs"],
                    result,
                    InformationType.FAQS,
                    variant=state.variant.id,
                    user_language=user_language,
                    base_url=base_url,
                )

            # Add lecture content citations
            lecture_content_storage = getattr(state, "lecture_content_storage", {})
            if lecture_content_storage.get("content"):
                state.callback.in_progress("Adding lecture references...")
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    lecture_content_storage["content"],
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
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
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
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
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
            if self.context is not ChatContext.EXERCISE:
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
            llm_small = IrisLangchainChatModel(
                request_handler=ModelVersionRequestHandler(version="gpt-4.1-mini"),
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
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
        result: str,
    ) -> None:
        """
        Generate interaction suggestions. This is only available ChatContext.COURSE, ChatContext.EXERCISE.

        Args:
            state: The current pipeline execution state.
            result: The final result string.
        """
        if self.context not in {ChatContext.COURSE, ChatContext.EXERCISE}:
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
        variant: ChatVariant,
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
            super().__call__(dto, variant, callback)

        except Exception as e:
            logger.error(
                "An error occurred while running the chat pipeline.", exc_info=e
            )
            callback.error("An error occurred while running the chat pipeline.")
