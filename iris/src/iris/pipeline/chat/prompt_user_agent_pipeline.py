import logging
import os
from datetime import datetime
from typing import Any, Callable, List

import pytz
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langsmith import traceable

from ...common.memiris_setup import get_tenant_for_user
from ...domain.chat.prompt_user_chat.prompt_user_chat_pipeline_execution_dto import PromptUserChatPipelineExecutionDTO
from ...domain.variant.prompt_user_variant import PromptUserVariant
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ...tools import (
    create_tool_file_lookup,
    create_tool_get_additional_exercise_details,
    create_tool_get_build_logs_analysis,
    create_tool_get_feedbacks,
    create_tool_get_submission_details,
    create_tool_lecture_content_retrieval,
    create_tool_repository_files,
)
from ...web.status.status_update import PromptUserStatusCallback
from ..abstract_agent_pipeline import AbstractAgentPipeline, AgentPipelineExecutionState
from ..shared.utils import datetime_to_string

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class PromptUserAgentPipeline(
    AbstractAgentPipeline[PromptUserChatPipelineExecutionDTO, PromptUserVariant]
):
    """
    Exercise chat agent pipeline that assesses the authenticity of user submissions by generating questions and assessing the answers by the user.
    """

    # assess_user_answer_pipeline: AssessUserAnswerPipeline
    jinja_env: Environment
    system_prompt_template: Any
    guide_prompt_template: Any

    def __init__(self):
        """
        Initialize the prompt user agent pipeline.
        """
        super().__init__(implementation_id="prompt_user_chat_pipeline")

        # Create the pipelines
        # self.assess_user_answer_pipeline = AssessUserAnswerPipeline()

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["j2"])
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "prompt_user_chat_system_prompt.j2"
        )
        self.guide_prompt_template = self.jinja_env.get_template(
            "prompt_user_chat_guide_prompt.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __str__(self):
        return f"{self.__class__.__name__}()"

    @classmethod
    def get_variants(cls) -> List[PromptUserVariant]:  # type: ignore[override]
        """
        Get available variants for the prompt user chat pipeline.

        Returns:
            List of ExerciseChatVariant instances.
        """
        return [
            PromptUserVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini"
            ),
            PromptUserVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1"
            ),
        ]


    def is_memiris_memory_creation_enabled(
                self,
                state: AgentPipelineExecutionState[
                    PromptUserChatPipelineExecutionDTO, PromptUserVariant
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


    def get_memiris_tenant(self, dto: PromptUserChatPipelineExecutionDTO) -> str:
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
                PromptUserChatPipelineExecutionDTO, PromptUserVariant
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
        callback = state.callback
        dto = state.dto

        # Initialize storage for shared data between tools
        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})

        lecture_content_storage = getattr(state, "lecture_content_storage")

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

        return tool_list

    def build_system_message(
            self,
            state: AgentPipelineExecutionState[
                PromptUserChatPipelineExecutionDTO, PromptUserVariant
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

        problem_statement: str = dto.exercise.problem_statement if dto.exercise else ""
        exercise_title: str = dto.exercise.name if dto.exercise else ""
        programming_language = (
            dto.exercise.programming_language.lower()
            if dto.exercise and dto.exercise.programming_language
            else ""
        )

        # Build system prompt using Jinja2 template
        template_context = {
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "exercise_title": exercise_title,
            "problem_statement": problem_statement,
            "programming_language": programming_language,
            "event": self.event,
            "has_chat_history": len(state.message_history) > 0,
            "verdict": "" # TODO: replace this with verdict of assessment sub-pipeline
        }

        return self.system_prompt_template.render(template_context)

    def on_agent_step(
            self,
            state: AgentPipelineExecutionState[
                PromptUserChatPipelineExecutionDTO, PromptUserVariant
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

    def pre_agent_hook(
            self,
            state: AgentPipelineExecutionState[
                PromptUserChatPipelineExecutionDTO, PromptUserVariant
            ],
    ) -> str:
        """
        Process results before agent execution.

        Args:
            state: The current pipeline execution state.

        Returns:
            The processed result string.
        """
        # TODO: run assess_answer sub-pipeline (only if event says nothing else (e.g. build with points/user initiates prompting/timer ran out/tab defocus)) in pre-hook and give verdict as input for agent pipeline (set 'verdict' value to "next_question" like in build_system_message(...) corresponding to assessment result in state.prompt)
        # TODO: also send verdict and reasoning to artemis via callback


        """try:
            # Assess previous answer of user if existing
            self._assess_answer(state, result)

            state.callback.done("Done!", final_result=result, tokens=state.tokens)

            return result

        except Exception as e:
            logger.error("Error in pre agent hook", exc_info=e)
            state.callback.error("Error in processing response")
            return state.result"""
        pass


    def post_agent_hook(
            self,
            state: AgentPipelineExecutionState[
                PromptUserChatPipelineExecutionDTO, PromptUserVariant
            ],
    ) -> str:
        """
        Process results after agent execution.
        Args:
            state: The current pipeline execution state.

        Returns:
            The processed result string.
        """

        try: # TODO: only run refinement pipeline when actually a new question was generated (e.g. don't when verdict was suspicious/unsuspicious/clarify or event is build_with_points/timer/tab)
            # Refine response using guide prompt
            result = self._refine_response(state)

            state.callback.done("Done!", final_result=result, tokens=state.tokens)

            return result

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            state.callback.error("Error in processing response")
            return state.result


    def _refine_response(
            self,
            state: AgentPipelineExecutionState[
                PromptUserChatPipelineExecutionDTO, PromptUserVariant
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

            dto = state.dto

            problem_statement: str = dto.exercise.problem_statement if dto.exercise else ""
            programming_language = (
                dto.exercise.programming_language.lower()
                if dto.exercise and dto.exercise.programming_language
                else ""
            )

            template_context = {
                "problem_statement": problem_statement,
                "programming_language": programming_language
            }

            guide_prompt_rendered = self.guide_prompt_template.render(template_context)

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
                logger.info("Question is ok and not rewritten")
                return state.result
            else:
                logger.info("Question is rewritten")
                return guide_response

        except Exception as e:
            logger.error("Error in refining question", exc_info=e)
            state.callback.error("Error in refining question")
            return state.result



    def _assess_answer( #TODO: run sub-pipeline
            self,
            state: AgentPipelineExecutionState[
                PromptUserChatPipelineExecutionDTO, PromptUserVariant
            ],
            result: str,
    ) -> None:
        """
        Generate interaction suggestions.

        Args:
            state: The current pipeline execution state.
            result: The final result string.
        """
        """try:
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
            state.callback.error("Generating interaction suggestions failed.")"""


    @traceable(name="Prompt User Agent Pipeline")
    def __call__(
            self,
            dto: PromptUserChatPipelineExecutionDTO,
            variant: PromptUserVariant,
            callback: PromptUserStatusCallback,
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
            logger.info("Running prompt user pipeline...")

            self.event = event

            # Delegate to parent class for standardized execution
            super().__call__(dto, variant, callback)


        except Exception as e:
            logger.error("Error in prompt user pipeline", exc_info=e)
            callback.error(
                "An error occurred while running the prompt user pipeline."
            )
