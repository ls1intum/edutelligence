import os
from datetime import datetime
from enum import StrEnum, auto
from typing import Any, Callable, List, Optional, cast

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from iris.common.logging_config import get_logger
from iris.common.memiris_setup import get_tenant_for_user
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain import ChatPipelineExecutionDTO, ExerciseChatPipelineExecutionDTO
from iris.domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from iris.domain.variant.chat_variant import ChatVariant
from iris.domain.variant.exercise_chat_variant import ExerciseChatVariant
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.pipeline.chat.code_feedback_pipeline import CodeFeedbackPipeline
from iris.pipeline.chat.interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)
from iris.pipeline.shared.citation_pipeline import CitationPipeline, InformationType
from iris.pipeline.shared.utils import (
    datetime_to_string,
    format_custom_instructions,
)
from iris.retrieval.faq_retrieval import FaqRetrieval
from iris.retrieval.faq_retrieval_utils import should_allow_faq_tool
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from iris.tools import (
    create_tool_faq_content_retrieval,
    create_tool_file_lookup,
    create_tool_get_additional_exercise_details,
    create_tool_get_build_logs_analysis,
    create_tool_get_feedbacks,
    create_tool_get_submission_details,
    create_tool_lecture_content_retrieval,
    create_tool_repository_files,
)
from iris.tracing import observe
from iris.web.status.status_update import ExerciseChatStatusCallback, StatusCallback

logger = get_logger(__name__)


class ChatContext(StrEnum):
    COURSE = auto()
    LECTURE = auto()
    EXERCISE = auto()
    TEXT_EXERCISE = auto()


class ChatPipeline(AbstractAgentPipeline[ChatPipelineExecutionDTO, ChatVariant]):
    """
    Replaces CourseChatPipeline / ExerciseChatPipeline / TextExerciseChatPipeline / LectureChatPipeline
    """

    # Shared
    context: ChatContext
    session_title_pipeline: SessionTitleGenerationPipeline
    citation_pipeline: CitationPipeline
    jinja_env: Environment
    system_prompt_template: Any

    # Context-Specific
    lecture_retriever: Optional[LectureRetrieval]
    faq_retriever: Optional[FaqRetrieval]
    suggestion_pipeline: Optional[InteractionSuggestionPipeline]
    event: Optional[str]
    code_feedback_pipeline: Optional[CodeFeedbackPipeline]
    guide_prompt_template: Any  # TODO: Remove ?

    def __init__(
        self,
        context: ChatContext,
        event: Optional[str] = None,
    ):
        super().__init__(implementation_id="chat_pipeline")

        self.context = context

        self.event = None

        # Initialize pipelines & retrievers
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.citation_pipeline = CitationPipeline()
        self.suggestion_pipeline = None
        self.code_feedback_pipeline = None
        self.lecture_retriever = None
        self.faq_retriever = None

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "exercise_chat_system_prompt.j2"
        )
        self.guide_prompt_template = None

        # Setup context-specific components
        if self.context == ChatContext.COURSE:
            self.suggestion_pipeline = InteractionSuggestionPipeline(
                variant=self.context
            )
            self.event = event

        elif self.context == ChatContext.EXERCISE:
            self.suggestion_pipeline = InteractionSuggestionPipeline(
                variant=self.context
            )
            self.code_feedback_pipeline = CodeFeedbackPipeline()
            self.guide_prompt_template = self.jinja_env.get_template(
                "exercise_chat_guide_prompt.j2"
            )

    def __repr__(self):
        if self.context == ChatContext.COURSE:
            return f"{self.__class__.__name__}(event={self.event})"
        else:
            return f"{self.__class__.__name__}()"

    def __str__(self):
        if self.context == ChatContext.COURSE:
            return f"{self.__class__.__name__}(event={self.event})"
        else:
            return f"{self.__class__.__name__}()"

    @classmethod
    def get_variants(cls, context: Optional[ChatContext] = None) -> List[ChatVariant]:
        """
        Get available variants for the chat pipeline.

        Args:
            context: If provided, only return variants for this context.
                     If None, returns variants for Exercise context (default for now).

        Returns:
            List[ChatVariant]: List of available variants
        """
        # For now, if no context specified, default to EXERCISE (backwards compatibility)
        if context is None:
            context = ChatContext.EXERCISE

        # Define all variants
        all_variants = {
            ChatContext.COURSE: [
                ChatVariant(
                    variant_id="default",
                    name="Default",
                    description="Uses a smaller model for faster and cost-efficient course responses.",
                    agent_model="gpt-4.1-mini",
                    citation_model="gpt-4.1-mini",
                ),
                ChatVariant(
                    variant_id="advanced",
                    name="Advanced",
                    description="Uses a larger chat model for course responses.",
                    agent_model="gpt-4.1",
                    citation_model="gpt-4.1-mini",
                ),
            ],
            ChatContext.EXERCISE: [
                ChatVariant(
                    variant_id="default",
                    name="Default",
                    description="Uses a smaller model for faster and cost-efficient responses.",
                    agent_model="gpt-4.1-mini",
                    citation_model="gpt-4.1-mini",
                ),
                ChatVariant(
                    variant_id="advanced",
                    name="Advanced",
                    description="Uses a larger chat model, balancing speed and quality.",
                    agent_model="gpt-4.1",
                    citation_model="gpt-4.1-mini",
                ),
            ],
            ChatContext.LECTURE: [
                ChatVariant(
                    variant_id="default",
                    name="Default",
                    description="Uses a smaller model for faster lecture responses.",
                    agent_model="gpt-4.1-mini",
                    citation_model="gpt-4.1-mini",
                ),
                ChatVariant(
                    variant_id="advanced",
                    name="Advanced",
                    description="Uses a larger model for better lecture explanations.",
                    agent_model="gpt-4.1",
                    citation_model="gpt-4.1-mini",
                ),
            ],
            ChatContext.TEXT_EXERCISE: [
                ChatVariant(
                    variant_id="default",
                    name="Default",
                    description="Uses a smaller model for faster text exercise responses.",
                    agent_model="gpt-4.1-mini",
                    citation_model="gpt-4.1-mini",
                ),
                ChatVariant(
                    variant_id="advanced",
                    name="Advanced",
                    description="Uses a larger model for better text exercise feedback.",
                    agent_model="gpt-4.1",
                    citation_model="gpt-4.1-mini",
                ),
            ],
        }

        return all_variants.get(context, [])

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
                for m in reversed(dto.chat_history or [])  # TODO: Check with Phoebe
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
        return get_tenant_for_user(
            dto.user.id
        )  # TODO: Phoebe fragen für TextExercise case

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
            state.callback.in_progress(
                "Thinking ..."
            )  # TODO: Text_Exercise= Thinking about your question...

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
            )  # TODO: Memiris ?

            # Generate and send suggestions separately (async from user's perspective)
            if self.context in [
                ChatContext.COURSE,
                ChatContext.EXERCISE,
            ]:  # TODO: Text_Exercise? Lecture?
                self._generate_suggestions(state, result)

            return result

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            state.callback.error("Error in processing response")
            return state.result

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
        ],
    ) -> list[Callable]:
        """
        Create and return tools for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            List of tool functions for the agent.
        """
        query_text = self.get_text_of_latest_user_message(state)
        callback = cast(ExerciseChatStatusCallback, state.callback)
        dto = state.dto

        # Initialize storage for shared data between tools
        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})

        lecture_content_storage = getattr(state, "lecture_content_storage")
        faq_storage = getattr(state, "faq_storage")

        # Build tool list based on available data and permissions
        tool_list: list[Callable] = [
            create_tool_get_submission_details(dto.submission, callback),
            create_tool_get_additional_exercise_details(dto.exercise, callback),
            create_tool_get_build_logs_analysis(dto.submission, callback),
            create_tool_get_feedbacks(dto.submission, callback),
            create_tool_repository_files(
                dto.submission.repository if dto.submission else None, callback
            ),
            create_tool_file_lookup(
                dto.submission.repository if dto.submission else None, callback
            ),
        ]

        # Add lecture content retrieval if available
        if should_allow_lecture_tool(state.db, dto.course.id):
            lecture_retriever = LectureRetrieval(state.db.client)
            tool_list.append(
                create_tool_lecture_content_retrieval(
                    lecture_retriever,
                    dto.course.id,
                    dto.settings.artemis_base_url if dto.settings else "",
                    callback,
                    query_text,
                    state.message_history,
                    lecture_content_storage,
                )
            )

        # Add FAQ retrieval if available
        if should_allow_faq_tool(state.db, dto.course.id):
            faq_retriever = FaqRetrieval(state.db.client)
            tool_list.append(
                create_tool_faq_content_retrieval(
                    faq_retriever,
                    dto.course.id,
                    dto.course.name,
                    dto.settings.artemis_base_url if dto.settings else "",
                    callback,
                    query_text,
                    state.message_history,
                    faq_storage,
                )
            )

        return tool_list

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
        ],
    ) -> str:
        """
        Build the system message/prompt for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            The system prompt string.
        """
        dto = state.dto
        query = self.get_latest_user_message(state)

        # Extract user language with fallback
        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        problem_statement: str = dto.exercise.problem_statement if dto.exercise else ""
        exercise_title: str = dto.exercise.name if dto.exercise else ""
        programming_language = (
            dto.exercise.programming_language.lower()
            if dto.exercise and dto.exercise.programming_language
            else ""
        )

        custom_instructions = format_custom_instructions(
            custom_instructions=dto.custom_instructions or ""
        )

        # Build system prompt using Jinja2 template
        template_context = {
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "user_language": user_language,
            "exercise_title": exercise_title,
            "problem_statement": problem_statement,
            "programming_language": programming_language,
            "event": self.event,
            "has_query": query is not None,
            "has_chat_history": len(state.message_history) > 0,
            "custom_instructions": custom_instructions,
        }

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
        match self.context:
            case ChatContext.COURSE:
                return bool(state.dto.user and state.dto.user.memiris_enabled)
            case ChatContext.LECTURE:
                return bool(state.dto.user and state.dto.user.memiris_enabled)
            case ChatContext.EXERCISE:
                return False
            case ChatContext.TEXT_EXERCISE:
                return False
            case _:
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
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ChatVariant
        ],
    ) -> str:
        """
        Refine the agent response using the guide prompt.

        Args:
            state: The current pipeline execution state.

        Returns:
            The refined response.
        """
        try:
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
        Generate interaction suggestions.

        Args:
            state: The current pipeline execution state.
            result: The final result string.
        """
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

    @observe(name="Exercise Chat Agent Pipeline")
    def __call__(
        self,
        dto: ChatPipelineExecutionDTO,
        variant: ChatVariant,
        callback: StatusCallback,
        event: str | None,
    ):
        """
        Execute the pipeline with the provided arguments.

        Args:
            dto: Execution data transfer object.
            variant: The variant configuration to use.
            callback: Status callback for progress updates.
        """
        try:
            logger.info("Running exercise chat pipeline...")

            self.event = event

            # Delegate to parent class for standardized execution
            super().__call__(dto, variant, callback)

        except Exception as e:
            logger.error("Error in exercise chat pipeline", exc_info=e)
            callback.error(
                "An error occurred while running the exercise chat pipeline."
            )
