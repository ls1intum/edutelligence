import os
from enum import Enum, StrEnum, auto
from typing import Any, Callable, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from iris.common.logging_config import get_logger
from iris.common.memiris_setup import get_tenant_for_user
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain import (
    ChatPipelineExecutionDTO,
    CourseChatPipelineExecutionDTO,
    ExerciseChatPipelineExecutionDTO,
)
from iris.domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from iris.domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from iris.domain.chat.text_exercise_chat.text_exercise_chat_pipeline_execution_dto import (
    TextExerciseChatPipelineExecutionDTO,
)
from iris.domain.variant.chat_variant import ChatVariant
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.pipeline.chat.code_feedback_pipeline import CodeFeedbackPipeline
from iris.pipeline.chat.course_chat_pipeline import CourseChatPipeline
from iris.pipeline.chat.exercise_chat_agent_pipeline import ExerciseChatAgentPipeline
from iris.pipeline.chat.interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)
from iris.pipeline.chat.lecture_chat_pipeline import LectureChatPipeline
from iris.pipeline.chat.text_exercise_chat_pipeline import TextExerciseChatPipeline
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)
from iris.pipeline.shared.citation_pipeline import CitationPipeline, InformationType
from iris.retrieval.faq_retrieval import FaqRetrieval
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.tracing import observe
from iris.web.status.status_update import StatusCallback

logger = get_logger(__name__)


class ToolType(Enum):
    """
    Enum that defines all the available tools
    """

    COURSE_DETAILS = auto()
    LECTURE_CONTENT = auto()
    FAQ_CONTENT = auto()
    EXERCISE_LIST = auto()
    STUDENT_EXERCISE_METRICS = auto()
    COMPETENCY_LIST = auto()
    MEMORY_SEARCH = auto()
    SUBMISSION_DETAILS = auto()
    BUILD_LOGS_ANALYSIS = auto()
    FEEDBACKS = auto()
    REPOSITORY_FILES = auto()
    FILE_LOOKUP = auto()
    SCOPED_LECTURE_ID = auto()
    ADDITIONAL_EXERCISE_DETAILS = auto()
    EXERCISE_PROBLEM_STATEMENT = auto()


class ChatContext(StrEnum):
    COURSE = auto()
    LECTURE = auto()
    EXERCISE = auto()
    TEXT_EXERCISE = auto()

    @property
    def available_tools(self) -> list[ToolType]:
        match self:
            case ChatContext.COURSE:
                return [
                    ToolType.COURSE_DETAILS,
                    ToolType.LECTURE_CONTENT,
                    ToolType.FAQ_CONTENT,
                    ToolType.EXERCISE_LIST,
                    ToolType.STUDENT_EXERCISE_METRICS,
                    ToolType.COMPETENCY_LIST,
                    ToolType.MEMORY_SEARCH,
                    ToolType.ADDITIONAL_EXERCISE_DETAILS,
                    ToolType.EXERCISE_PROBLEM_STATEMENT,
                ]
            case ChatContext.LECTURE:
                return [
                    ToolType.COURSE_DETAILS,
                    ToolType.LECTURE_CONTENT,
                    ToolType.FAQ_CONTENT,
                    ToolType.MEMORY_SEARCH,
                    ToolType.SCOPED_LECTURE_ID,
                ]
            case ChatContext.EXERCISE:
                return [
                    ToolType.LECTURE_CONTENT,
                    ToolType.FAQ_CONTENT,
                    ToolType.SUBMISSION_DETAILS,
                    ToolType.BUILD_LOGS_ANALYSIS,
                    ToolType.FEEDBACKS,
                    ToolType.REPOSITORY_FILES,
                    ToolType.FILE_LOOKUP,
                ]
            case ChatContext.TEXT_EXERCISE:
                return [
                    ToolType.COURSE_DETAILS,
                    ToolType.LECTURE_CONTENT,
                    ToolType.FAQ_CONTENT,
                ]


class ChatPipeline(AbstractAgentPipeline[ChatPipelineExecutionDTO, ChatVariant]):
    """
    Replaces CourseChatPipeline / ExerciseChatPipeline / TextExerciseChatPipeline / LectureChatPipeline
    """

    # Just for now -> See get_tools & build_message
    exercise_pipeline: ExerciseChatAgentPipeline
    course_pipeline: CourseChatPipeline
    text_exercise_pipeline: TextExerciseChatPipeline
    lecture_pipeline: LectureChatPipeline

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

        self.event = event  # TODO: Was hat es mit dem Event auf sich ?

        # Just for now -> See get_tools & build_message
        self.exercise_pipeline = ExerciseChatAgentPipeline()
        self.course_pipeline = CourseChatPipeline(event=event)
        self.text_exercise_pipeline = TextExerciseChatPipeline()
        self.lecture_pipeline = LectureChatPipeline()

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
        # Setup system prompt
        # Just for now
        match self.context:
            case ChatContext.COURSE:
                self.system_prompt_template = self.jinja_env.get_template(
                    "course_chat_system_prompt.j2"
                )
            case ChatContext.LECTURE:
                self.system_prompt_template = self.jinja_env.get_template(
                    "lecture_chat_system_prompt.j2"
                )
            case ChatContext.EXERCISE:
                self.system_prompt_template = self.jinja_env.get_template(
                    "exercise_chat_system_prompt.j2"
                )
            case ChatContext.TEXT_EXERCISE:
                self.system_prompt_template = self.jinja_env.get_template(
                    "text_exercise_chat_system_prompt.j2"
                )
        # self.system_prompt_template = self.jinja_env.get_template(
        #    "chat_system_prompt.j2" TODO: Prompts überarbeiten
        # )
        self.guide_prompt_template = None

        # Setup context-specific components
        if self.context == ChatContext.COURSE:
            self.suggestion_pipeline = InteractionSuggestionPipeline(
                variant=self.context
            )

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
    def get_variants(
        cls, context: Optional[ChatContext] = None
    ) -> List[ChatVariant]:  # TODO: Nur 2 Varianten für die Pipeline oder pro Kontext ?
        """
        Get available variants for the chat pipeline.

        Args:
            context: If provided, only return variants for this context.
                     If None, returns variants for Exercise context (default for now).

        Returns:
            List[ChatVariant]: List of available variants
        """
        # For now, if no context specified, default to EXERCISE
        if context is None:
            context = ChatContext.EXERCISE

        # Define all variants
        all_variants = {
            ChatContext.COURSE: [
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
                    description="Uses a smaller model for faster and cost-efficient responses.",
                    agent_model="gpt-4.1-mini",
                    citation_model="gpt-4.1-nano",
                ),
                ChatVariant(
                    variant_id="advanced",
                    name="Advanced",
                    description="Uses a larger chat model, balancing speed and quality.",
                    agent_model="gpt-4.1",
                    citation_model="gpt-4.1-mini",
                ),
            ],
            ChatContext.TEXT_EXERCISE: [
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

    def get_tools(  # TODO: Überarbeiten
        self,
        state: AgentPipelineExecutionState[ChatPipelineExecutionDTO, ChatVariant],
    ) -> list[Callable]:
        """
        Create and return tools for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            List of tool functions for the agent.
        """
        if (
            isinstance(state.dto, ExerciseChatPipelineExecutionDTO)
            and self.context == ChatContext.EXERCISE
        ):
            return self.exercise_pipeline.get_tools(state)
        elif (
            isinstance(state.dto, TextExerciseChatPipelineExecutionDTO)
            and self.context == ChatContext.TEXT_EXERCISE
        ):
            return self.text_exercise_pipeline.get_tools(state)
        elif (
            isinstance(state.dto, LectureChatPipelineExecutionDTO)
            and self.context == ChatContext.LECTURE
        ):
            return self.lecture_pipeline.get_tools(state)
        elif (
            isinstance(state.dto, CourseChatPipelineExecutionDTO)
            and self.context == ChatContext.COURSE
        ):
            return self.course_pipeline.get_tools(state)
        else:
            return []

    def build_system_message(  # TODO: Überarbeiten
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
        if (
            isinstance(state.dto, ExerciseChatPipelineExecutionDTO)
            and self.context == ChatContext.EXERCISE
        ):
            return self.exercise_pipeline.build_system_message(state)
        elif (
            isinstance(state.dto, TextExerciseChatPipelineExecutionDTO)
            and self.context == ChatContext.TEXT_EXERCISE
        ):
            return self.text_exercise_pipeline.build_system_message(state)
        elif (
            isinstance(state.dto, LectureChatPipelineExecutionDTO)
            and self.context == ChatContext.LECTURE
        ):
            return self.lecture_pipeline.build_system_message(state)
        elif (
            isinstance(state.dto, CourseChatPipelineExecutionDTO)
            and self.context == ChatContext.COURSE
        ):
            return self.course_pipeline.build_system_message(state)
        else:
            return []

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

    @observe(name="Chat Pipeline")
    def __call__(
        self,
        dto: ChatPipelineExecutionDTO,
        variant: ChatVariant,
        callback: StatusCallback,
        event: str | None,  # TODO: Nötig?
    ):
        """
        Execute the pipeline with the provided arguments.

        Args:
            dto: Execution data transfer object.
            variant: The variant configuration to use.
            callback: Status callback for progress updates.
        """
        try:
            logger.info("Running chat pipeline...")

            if self.context == ChatContext.EXERCISE and event:
                self.event = event

            # Delegate to parent class for standardized execution
            super().__call__(dto, variant, callback)

        except Exception as e:
            logger.error(
                "An error occurred while running the chat pipeline.", exc_info=e
            )
            callback.error(
                "An error occurred while running the chat pipeline.",
                tokens=(
                    []
                    if self.context in [ChatContext.COURSE, ChatContext.LECTURE]
                    else None
                ),
            )  # TODO: Tokens?

    # TODO: Folgende Methoden in TextExercisePipeline anschauen
    # get_recent_history_from_dto()
    # get_text_of_latest_user_message()
