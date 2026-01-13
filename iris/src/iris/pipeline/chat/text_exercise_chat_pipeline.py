import os
from datetime import datetime
from typing import Any, Callable, List, Optional

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langsmith import traceable

from iris.common.logging_config import get_logger
from iris.domain.chat.text_exercise_chat.text_exercise_chat_pipeline_execution_dto import (
    TextExerciseChatPipelineExecutionDTO,
)
from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)

from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain.variant.text_exercise_chat_variant import TextExerciseChatVariant
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ...tools import (
    create_tool_faq_content_retrieval,
    create_tool_get_course_details,
    create_tool_lecture_content_retrieval,
)
from ...web.status.status_update import TextExerciseChatCallback
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..session_title_relevance_pipeline import SessionTitleRelevancePipeline
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import datetime_to_string, format_custom_instructions

logger = get_logger(__name__)


class TextExerciseChatPipeline(
    AbstractAgentPipeline[TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant]
):
    """
    Text exercise chat pipeline that answers text exercise related questions from students.
    Uses an agent-based approach with tools for accessing course content, lectures, and FAQs.
    """

    session_title_pipeline: SessionTitleGenerationPipeline
    session_title_relevance_pipeline: SessionTitleRelevancePipeline
    citation_pipeline: CitationPipeline
    jinja_env: Environment
    system_prompt_template: Any

    def __init__(self):
        """
        Initialize the text exercise chat pipeline.
        """
        super().__init__(implementation_id="text_exercise_chat_pipeline")

        # Initialize pipelines
        self.citation_pipeline = CitationPipeline()
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.session_title_relevance_pipeline = SessionTitleRelevancePipeline()

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["j2"]),
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "text_exercise_chat_system_prompt.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __str__(self):
        return f"{self.__class__.__name__}()"

    @classmethod
    def get_variants(cls) -> List[TextExerciseChatVariant]:  # type: ignore[override]
        """
        Get available variants for the text exercise chat pipeline.

        Returns:
            List of TextExerciseChatVariant instances.
        """
        return [
            TextExerciseChatVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini",
            ),
            TextExerciseChatVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1",
            ),
        ]

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
        ],
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Args:
            state: The current pipeline execution state.

        Returns:
            False for now, can be enabled later.
        """
        return False

    def get_memiris_tenant(self, dto: TextExerciseChatPipelineExecutionDTO) -> str:
        """
        Return the Memiris tenant identifier for the current user.

        Args:
            dto: The execution DTO.

        Returns:
            A default tenant string (could be enhanced with user info if available).
        """
        # Since TextExerciseChatPipelineExecutionDTO doesn't have user info,
        # return a default tenant or extract from execution if available
        return "default_text_exercise_tenant"

    def get_memiris_reference(self, dto: TextExerciseChatPipelineExecutionDTO):
        """
        Return the reference to use for the Memiris learnings created in a text exercise chat.
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

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
        ],
    ) -> list[Callable]:
        """
        Create and return tools for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            List of tool functions for the agent.
        """
        dto = state.dto
        callback = state.callback

        # Initialize storage for shared data between tools
        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})

        lecture_content_storage = getattr(state, "lecture_content_storage")
        faq_storage = getattr(state, "faq_storage")

        # Build tool list
        tool_list: list[Callable] = []

        # Add course details tool
        if dto.exercise and dto.exercise.course:
            tool_list.append(
                create_tool_get_course_details(dto.exercise.course, callback)
            )

        # Add lecture content retrieval if available
        if dto.exercise and dto.exercise.course and dto.exercise.course.id:
            if should_allow_lecture_tool(state.db, dto.exercise.course.id):
                lecture_retriever = LectureRetrieval(state.db.client)
                query_text = self.get_text_of_latest_user_message(state)
                tool_list.append(
                    create_tool_lecture_content_retrieval(
                        lecture_retriever,
                        dto.exercise.course.id,
                        (dto.settings.artemis_base_url if dto.settings else ""),
                        callback,
                        query_text,
                        state.message_history,
                        lecture_content_storage,
                    )
                )

        # Add FAQ retrieval if available
        if dto.exercise and dto.exercise.course and dto.exercise.course.id:
            if should_allow_faq_tool(state.db, dto.exercise.course.id):
                faq_retriever = FaqRetrieval(state.db.client)
                query_text = self.get_text_of_latest_user_message(state)
                tool_list.append(
                    create_tool_faq_content_retrieval(
                        faq_retriever,
                        dto.exercise.course.id,
                        dto.exercise.course.name,
                        (dto.settings.artemis_base_url if dto.settings else ""),
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
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
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

        # Extract user language with fallback
        user_language = "en"
        if state.dto.user and state.dto.user.lang_key:
            user_language = state.dto.user.lang_key

        exercise_title = dto.exercise.title if dto.exercise else ""
        course_name = (
            dto.exercise.course.name if dto.exercise and dto.exercise.course else ""
        )
        problem_statement = dto.exercise.problem_statement if dto.exercise else ""
        start_date = (
            str(dto.exercise.start_date)
            if dto.exercise and dto.exercise.start_date
            else ""
        )
        end_date = (
            str(dto.exercise.end_date) if dto.exercise and dto.exercise.end_date else ""
        )

        # Extract custom instructions if available from execution
        custom_instructions = ""
        if hasattr(dto, "settings") and dto.settings:
            custom_instructions = getattr(dto.settings, "custom_instructions", "")

        custom_instructions = format_custom_instructions(custom_instructions)

        # Build system prompt using Jinja2 template
        template_context = {
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "user_language": user_language,
            "exercise_id": dto.exercise.id if dto.exercise else "",
            "exercise_title": exercise_title,
            "course_name": course_name,
            "problem_statement": problem_statement,
            "start_date": start_date,
            "end_date": end_date,
            "current_submission": dto.current_submission,
            "custom_instructions": custom_instructions,
        }

        return self.system_prompt_template.render(template_context)

    def get_recent_history_from_dto(
        self,
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
        ],
        limit: int | None = None,
    ) -> list[PyrisMessage]:
        """
        Convert the chat_history from DTO to message history format.

        Args:
            state: The current pipeline execution state.
            limit: Optional limit on number of messages.

        Returns:
            List of PyrisMessage objects.
        """
        # Use the chat_history field from the DTO
        chat_history = state.dto.chat_history or []
        effective_limit = limit if limit is not None else self.get_history_limit(state)
        return chat_history[-effective_limit:] if chat_history else []

    def get_text_of_latest_user_message(
        self,
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
        ],
    ) -> str:
        """
        Extract the latest user's text input from the chat_history.

        Args:
            state: The current pipeline execution state.

        Returns:
            The text content of the latest user message.
        """
        if state.dto.chat_history:
            # Get the last message in the chat_history
            last_message = state.dto.chat_history[-1]
            if last_message.sender == IrisMessageRole.USER and last_message.contents:
                # Extract text content
                if isinstance(last_message.contents[0], dict):
                    return last_message.contents[0].get("text_content", "")
                elif isinstance(last_message.contents[0], TextMessageContentDTO):
                    return last_message.contents[0].text_content
        return ""

    def on_agent_step(
        self,
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
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
            state.callback.in_progress("Thinking about your question...")

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
        ],
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

            # Add citations if applicable
            result = self._add_citations(state, result)

            # Generate title
            session_title = self._generate_session_title(state, state.result, state.dto)

            # Update final callback with tokens
            state.callback.done(
                "Response completed",
                final_result=result,
                tokens=state.tokens,
                session_title=session_title,
            )

            return result

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            state.callback.error("Error in processing response")
            return state.result

    def _add_citations(
        self,
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
        ],
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
        state: AgentPipelineExecutionState[
            TextExerciseChatPipelineExecutionDTO, TextExerciseChatVariant
        ],
        output: str,
        dto: TextExerciseChatPipelineExecutionDTO,
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

    @traceable(name="Text Exercise Chat Pipeline")
    def __call__(
        self,
        dto: TextExerciseChatPipelineExecutionDTO,
        variant: TextExerciseChatVariant,
        callback: TextExerciseChatCallback,
        **kwargs,
    ):
        """
        Execute the pipeline with the provided arguments.

        Args:
            dto: Execution data transfer object.
            variant: The variant configuration to use.
            callback: Status callback for progress updates (REQUIRED).
        """
        try:
            logger.info("Running text exercise chat pipeline...")

            # Delegate to parent class for standardized execution
            super().__call__(dto, variant, callback)

        except Exception as e:
            logger.error("Error in text exercise chat pipeline", exc_info=e)
            if callback:
                callback.error(
                    "An error occurred while running the text exercise chat pipeline."
                )
