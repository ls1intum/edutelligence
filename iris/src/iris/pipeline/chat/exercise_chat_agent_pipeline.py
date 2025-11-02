import logging
import os
from datetime import datetime
from typing import Any, Callable, List, Optional, cast

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langsmith import traceable

from iris.pipeline.session_title_generation_pipeline import (
    SessionTitleGenerationPipeline,
)

from ...common.memiris_setup import get_tenant_for_user
from ...domain import ExerciseChatPipelineExecutionDTO
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.variant.exercise_chat_variant import ExerciseChatVariant
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ...tools import (
    create_tool_faq_content_retrieval,
    create_tool_file_lookup,
    create_tool_get_additional_exercise_details,
    create_tool_get_build_logs_analysis,
    create_tool_get_feedbacks,
    create_tool_get_submission_details,
    create_tool_lecture_content_retrieval,
    create_tool_repository_files,
)
from ...web.status.status_update import ExerciseChatStatusCallback
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import datetime_to_string, format_custom_instructions
from .code_feedback_pipeline import CodeFeedbackPipeline
from .interaction_suggestion_pipeline import InteractionSuggestionPipeline

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ExerciseChatAgentPipeline(
    AbstractAgentPipeline[ExerciseChatPipelineExecutionDTO, ExerciseChatVariant]
):
    """
    Exercise chat agent pipeline that answers exercises related questions from students.
    """

    session_title_pipeline: SessionTitleGenerationPipeline
    suggestion_pipeline: InteractionSuggestionPipeline
    code_feedback_pipeline: CodeFeedbackPipeline
    citation_pipeline: CitationPipeline
    jinja_env: Environment
    system_prompt_template: Any
    guide_prompt_template: Any

    def __init__(self):
        """
        Initialize the exercise chat agent pipeline.
        """
        super().__init__(implementation_id="exercise_chat_pipeline")

        # Create the pipelines
        self.session_title_pipeline = SessionTitleGenerationPipeline()
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant="exercise")
        self.code_feedback_pipeline = CodeFeedbackPipeline()
        self.citation_pipeline = CitationPipeline()

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
        self.guide_prompt_template = self.jinja_env.get_template(
            "exercise_chat_guide_prompt.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __str__(self):
        return f"{self.__class__.__name__}()"

    @classmethod
    def get_variants(cls) -> List[ExerciseChatVariant]:  # type: ignore[override]
        """
        Get available variants for the exercise chat pipeline.

        Returns:
            List of ExerciseChatVariant instances.
        """
        return [
            ExerciseChatVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini",
                citation_model="gpt-4.1-mini",
            ),
            ExerciseChatVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1",
                citation_model="gpt-4.1-mini",
            ),
        ]

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
        ],
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Args:
            state: The current pipeline execution state.

        Returns:
            True if memory creation should be enabled, False otherwise.
        """
        return False

    def get_memiris_tenant(self, dto: ExerciseChatPipelineExecutionDTO) -> str:
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
            "exercise_title": exercise_title,
            "problem_statement": problem_statement,
            "programming_language": programming_language,
            "event": self.event,
            "has_query": query is not None,
            "has_chat_history": len(state.message_history) > 0,
            "custom_instructions": custom_instructions,
        }

        return self.system_prompt_template.render(template_context)

    def on_agent_step(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
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
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
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
            # Refine response using guide prompt
            result = self._refine_response(state)

            # Add citations if applicable
            result = self._add_citations(state, result)

            # Generate title
            session_title = self._generate_session_title(state, result, state.dto)

            # Generate suggestions
            self._generate_suggestions(state, result)

            state.callback.done(
                "Done!",
                final_result=result,
                tokens=state.tokens,
                session_title=session_title,
            )

            return result

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            state.callback.error("Error in processing response")
            return state.result

    def _refine_response(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
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

    def _add_citations(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
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
        try:
            # Add FAQ citations
            faq_storage = getattr(state, "faq_storage", {})
            if faq_storage.get("faqs"):
                state.callback.in_progress("Augmenting response ...")
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    faq_storage["faqs"],
                    result,
                    InformationType.FAQS,
                    variant=state.variant.id,
                    base_url=base_url,
                )

            # Add lecture content citations
            lecture_content_storage = getattr(state, "lecture_content_storage", {})
            if lecture_content_storage.get("content"):
                state.callback.in_progress("Augmenting response ...")
                base_url = (
                    state.dto.settings.artemis_base_url if state.dto.settings else ""
                )
                result = self.citation_pipeline(
                    lecture_content_storage["content"],
                    result,
                    InformationType.PARAGRAPHS,
                    variant=state.variant.id,
                    base_url=base_url,
                )

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

    def _generate_suggestions(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
        ],
        result: str,
    ) -> None:
        """
        Generate interaction suggestions.

        Args:
            state: The current pipeline execution state.
            result: The final result string.
        """
        try:
            if result:
                suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                suggestion_dto.chat_history = state.dto.chat_history
                suggestion_dto.last_message = result
                suggestions = self.suggestion_pipeline(suggestion_dto)

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

    def _generate_session_title(
        self,
        state: AgentPipelineExecutionState[
            ExerciseChatPipelineExecutionDTO, ExerciseChatVariant
        ],
        output: str,
        dto: ExerciseChatPipelineExecutionDTO,
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
        if self.should_generate_session_title(dto.session_title):
            user_msg = (
                dto.chat_history[len(dto.chat_history) - 1].contents[0].text_content
            )
            return super()._create_session_title(state, output, user_msg)
        return None

    @traceable(name="Exercise Chat Agent Pipeline")
    def __call__(
        self,
        dto: ExerciseChatPipelineExecutionDTO,
        variant: ExerciseChatVariant,
        callback: ExerciseChatStatusCallback,
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
