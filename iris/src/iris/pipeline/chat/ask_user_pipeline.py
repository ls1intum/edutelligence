import json
import logging
import os
from datetime import datetime
from typing import Any, Callable, List

import pytz
from jinja2 import Environment, FileSystemLoader
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langsmith import traceable

from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from ..prompts.templates.ask_user.verdict_dependent_placeholder import VERDICT_DEPENDENT

from ...common.memiris_setup import get_tenant_for_user
from ...domain.chat.ask_user_chat.ask_user_chat_pipeline_execution_dto import (
    AskUserPipelineExecutionDTO,
)
from ...domain.data.verdict_dto import VerdictDTO
from ...domain.variant.ask_user_variant import AskUserVariant
from ...tools import (
    create_tool_file_lookup,
    create_tool_get_additional_exercise_details,
    create_tool_get_build_logs_analysis,
    create_tool_get_feedbacks,
    create_tool_get_submission_details,
    create_tool_repository_files,
)
from ...web.status.status_update import AskUserStatusCallback
from ..abstract_agent_pipeline import (
    DTO,
    VARIANT,
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from ..shared.utils import datetime_to_string
from .assess_user_answer_pipeline import AssessUserAnswerPipeline

logger = logging.getLogger(__name__)


class AskUserPipeline(
    AbstractAgentPipeline[AskUserPipelineExecutionDTO, AskUserVariant]
):
    """
    Exercise chat agent pipeline that assesses the authenticity of user submissions by generating
    questions and assessing the answers by the user.
    """

    assess_user_answer_pipeline: AssessUserAnswerPipeline
    verdict: VerdictDTO | None
    jinja_env: Environment
    system_prompt_template: Any
    guide_prompt_template: Any
    verdict_dependent_template: Any

    def __init__(self, local: bool = False, variant: AskUserVariant | None = None):
        """
        Initialize the ask-user agent pipeline.

        Args:
            local: Whether to resolve models against the local/self-hosted
                configuration instead of the cloud configuration.
            variant: The variant selected for this request. Determines which
                assessment model is bound (e.g. "advanced" resolves to a
                larger model than "default"). Falls back to the "default"
                variant when not provided.
        """
        super().__init__(implementation_id="ask_user_chat_pipeline")

        # Create the assessment pipeline and its result variable
        selected_variant = variant or next(
            v for v in self.get_variants() if v.variant_id == "default"
        )
        self.assess_user_answer_pipeline = AssessUserAnswerPipeline(
            model=selected_variant.model("chat", local)
        )
        self.verdict = None

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates", "ask_user"
        )
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir), autoescape=False
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "ask_user_chat_system_prompt.j2"
        )
        self.guide_prompt_template = self.jinja_env.get_template(
            "ask_user_chat_guide_prompt.j2"
        )
        self.verdict_dependent_template = self.jinja_env.get_template(
            "verdict_dependent.j2"
        )

    def __repr__(self):
        return f"{self.__class__.__name__}()"

    def __str__(self):
        return f"{self.__class__.__name__}()"

    @classmethod
    def get_variants(cls) -> List[AskUserVariant]:  # type: ignore[override]
        """
        Get available variants for the ask-user chat pipeline.

        Returns:
            List of ExerciseChatVariant instances.
        """
        return [
            AskUserVariant(
                variant_id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="oai-gpt-5-mini",
                # Self-hosted counterpart, so LOCAL_AI actually stays on-prem
                # instead of silently falling back to the cloud OpenAI id.
                local_agent_model="gpt-oss",
            ),
            AskUserVariant(
                variant_id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="oai-gpt-52",
                guide_model="oai-gpt-5-mini",
                # gpt-oss is the only self-hosted chat model available; used
                # for both roles so LOCAL_AI never leaks student data to a
                # cloud provider.
                local_agent_model="gpt-oss",
                local_guide_model="gpt-oss",
            ),
        ]

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
    ) -> bool:
        """
        Return True if background memory creation should be enabled for this run.

        Args:
            state: The current pipeline execution state.

        Returns:
            True if memory creation should be enabled, False otherwise.
        """
        return False

    def get_memiris_tenant(self, dto: AskUserPipelineExecutionDTO) -> str:
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

    def get_memiris_reference(self, dto: AskUserPipelineExecutionDTO) -> str:
        """
        Does not return any reference, as memory creation is disabled for this pipeline.
        """
        return "unknown"

    @staticmethod
    def _get_exercise_title(dto: AskUserPipelineExecutionDTO) -> str:
        """
        Resolve the exercise title, falling back to the exercise name if no title is set.

        Args:
            dto: The execution DTO containing the programming exercise.

        Returns:
            The exercise title, or an empty string if no exercise is present.
        """
        if not dto.programming_exercise:
            return ""
        return getattr(dto.programming_exercise, "title", None) or getattr(
            dto.programming_exercise, "name", ""
        )

    def get_tools(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
    ) -> list[Callable]:
        """
        Create and return tools for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            List of tool functions for the agent.
        """
        callback = state.callback
        dto = state.dto

        # Build tool list based on available data and permissions
        tool_list: list[Callable] = [
            create_tool_get_submission_details(
                dto.programming_exercise_submission, callback
            ),
            create_tool_get_additional_exercise_details(
                dto.programming_exercise, callback
            ),
            create_tool_get_build_logs_analysis(
                dto.programming_exercise_submission, callback
            ),
            create_tool_get_feedbacks(dto.programming_exercise_submission, callback),
            create_tool_repository_files(
                (
                    dto.programming_exercise_submission.repository
                    if dto.programming_exercise_submission
                    else None
                ),
                callback,
            ),
            create_tool_file_lookup(
                (
                    dto.programming_exercise_submission.repository
                    if dto.programming_exercise_submission
                    else None
                ),
                callback,
            ),
        ]

        return tool_list

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
    ) -> str:
        """
        Build the system message/prompt for the agent.

        Args:
            state: The current pipeline execution state.

        Returns:
            The system prompt string.
        """
        dto = state.dto

        problem_statement: str = (
            dto.programming_exercise.problem_statement
            if dto.programming_exercise
            else ""
        )
        programming_language = (
            dto.programming_exercise.programming_language.lower()
            if dto.programming_exercise
            and dto.programming_exercise.programming_language
            else ""
        )
        exercise_title: str = self._get_exercise_title(dto)

        # Build system prompt using Jinja2 template (VERDICT_DEPENDENT and its context is replaced in pre_agent_hook)
        template_context = {
            "current_date": datetime_to_string(datetime.now(tz=pytz.UTC)),
            "event": self.event,
            "use_chat_history": self.chat_history_needed
            and len(state.message_history) > 0,
            "problem_statement": problem_statement,
            "programming_language": programming_language,
            "exercise_title": exercise_title,
            "user_language": dto.user.lang_key,
            "verdict_dependent_placeholder": VERDICT_DEPENDENT
        }

        return self.system_prompt_template.render(template_context)

    def on_agent_step(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
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
            state.callback.update()

    def pre_agent_hook(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
    ):
        """
        Process answer before agent execution.

        Args:
            state: The current pipeline execution state.

        Returns:
            The processed result string.
        """
        try:
            # Assess previous answer of user if no special event happened (e.g. quiz just started or timer ran out)
            if self.event is None:
                self._assess_answer(state)

        except Exception as e:
            logger.error("Error in pre agent hook", exc_info=e)
            state.callback.fail("Error in processing response")
            raise

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
    ):
        """
        Process results after agent execution.
        Args:
            state: The current pipeline execution state.

        Returns:
            The processed result string.
        """

        try:
            # Only run refinement pipeline when a new question was generated (only questions are refined)
            if self.event == "FIRST_QUESTION" or (
                self.verdict and self.verdict.verdict == "NEXT_QUESTION"
            ):
                # Refine response using guide prompt
                result = self._refine_response(state)
            else:
                result = state.result

            # Set verdict and reasoning manually in case of rule violations
            # (in these cases assessment pipeline is not run)
            if self.event == "TAB_DEFOCUS":
                self.verdict = VerdictDTO(
                    verdict="SUSPICIOUS", reasoning="Tab defocus!"
                )
            elif self.event == "TIMER_RAN_OUT":
                self.verdict = VerdictDTO(
                    verdict="SUSPICIOUS", reasoning="Time limit exceeded!"
                )

            # Set callback event
            if self.verdict:
                if (
                    self.verdict.verdict == "SUSPICIOUS"
                    or self.verdict.verdict == "UNSUSPICIOUS"
                ):
                    state.callback.status.event = "QUIZ_FINISHED"
                elif self.verdict.verdict == "NEXT_QUESTION":
                    state.callback.status.event = "NEXT_QUESTION"
                    # NEXT_QUESTION as verdict is not allowed by Artemis API
                    self.verdict.verdict = None
            else:
                # Pass event back to server
                state.callback.status.event = self.event

            state.callback.update(
                result=result, tokens=state.tokens, verdict=self.verdict
            )

        except Exception as e:
            logger.error("Error in post agent hook", exc_info=e)
            state.callback.fail("Error in processing response")

        # reset assessment result for next pipeline run
        self.verdict = None

    def _refine_response(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
    ) -> str:
        """
        Refine the agent response using the guide prompt.

        Args:
            state: The current pipeline execution state.

        Returns:
            The refined response.
        """
        try:
            state.callback.update()

            dto = state.dto

            problem_statement: str = (
                dto.programming_exercise.problem_statement
                if dto.programming_exercise
                else ""
            )
            programming_language = (
                dto.programming_exercise.programming_language.lower()
                if dto.programming_exercise
                and dto.programming_exercise.programming_language
                else ""
            )

            template_context = {
                "problem_statement": problem_statement,
                "programming_language": programming_language,
            }

            guide_prompt_rendered = self.guide_prompt_template.render(template_context)

            # Create small LLM for refinement
            completion_args = CompletionArguments(temperature=0.5, max_tokens=2000)
            llm_small = IrisLangchainChatModel(
                request_handler=LlmRequestHandler(
                    model_id=state.variant.model("guide", state.local)
                ),
                completion_args=completion_args,
            )

            prompt = ChatPromptTemplate.from_messages(
                [
                    SystemMessage(content=guide_prompt_rendered),
                    HumanMessage(content=state.result),
                ]
            )

            logger.info("Question before being rewritten:")
            logger.info(state.result)

            guide_response = (prompt | llm_small | StrOutputParser()).invoke({})

            self._track_tokens(state, llm_small.tokens)

            if "!ok!" in guide_response:
                logger.info("Question is ok and not rewritten")
                return state.result
            else:
                logger.info("Question is rewritten")
                logger.info("Question after being rewritten:")
                logger.info(guide_response)
                return guide_response

        except Exception as e:
            logger.error("Error in refining question", exc_info=e)
            state.callback.fail("Error in refining question")
            return state.result

    def _assess_answer(
        self,
        state: AgentPipelineExecutionState[AskUserPipelineExecutionDTO, AskUserVariant],
    ) -> None:
        """
        Assesses the last answer given by the user.

        Args:
            state: The current pipeline execution state.
        """
        try:
            assessment_result = self.assess_user_answer_pipeline(state.dto)

            start = assessment_result.find("{")
            end = assessment_result.rfind("}") + 1

            json_str = assessment_result[start:end]
            self.verdict = VerdictDTO(**json.loads(json_str))

            # Ugly workaround forced by architecture: we must mutate prompt messages after render
            # because the base class __call__ renders the prompt before we decide verdict in pre_agent_hook
            dto = state.dto
            problem_statement: str = (
                dto.programming_exercise.problem_statement
                if dto.programming_exercise
                else ""
            )
            exercise_title: str = self._get_exercise_title(dto)
            programming_language = (
                dto.programming_exercise.programming_language.lower()
                if dto.programming_exercise
                and dto.programming_exercise.programming_language
                else ""
            )
            template_context = {
                "verdict": self.verdict.verdict,
                "exercise_title": exercise_title,
                "problem_statement": problem_statement,
                "programming_language": programming_language
            }
            rendered_verdict_prompt = self.verdict_dependent_template.render(
                template_context
            )
            # Escape braces to make the prompt inert for LangChain templating
            rendered_verdict_prompt = rendered_verdict_prompt.replace(
                "{", "{{"
            ).replace("}", "}}")

            for msg in state.prompt.messages:
                if (
                    isinstance(msg, SystemMessagePromptTemplate)
                    and VERDICT_DEPENDENT in msg.prompt.template
                ):
                    msg.prompt.template = msg.prompt.template.replace(
                        VERDICT_DEPENDENT, rendered_verdict_prompt
                    )

            if self.assess_user_answer_pipeline.tokens is not None:
                self._track_tokens(state, self.assess_user_answer_pipeline.tokens)

        except Exception as e:
            logger.error("Error assessing answer", exc_info=e)
            state.callback.fail("Assessing answer failed.")
            raise

    def assemble_prompt_with_history(
        self, state: AgentPipelineExecutionState[DTO, VARIANT], system_prompt: str
    ) -> ChatPromptTemplate:
        """
        Combine the system prompt with chat history, omitting history when not needed.

        Args:
            state: The current pipeline execution state.
            system_prompt: The rendered system prompt.

        Returns:
            The assembled chat prompt template.
        """
        if not self.chat_history_needed:
            state.message_history = []

        return super().assemble_prompt_with_history(state, system_prompt)

    @traceable(name="Ask-user Agent Pipeline")
    def __call__(
        self,
        dto: AskUserPipelineExecutionDTO,
        variant: AskUserVariant,
        callback: AskUserStatusCallback,
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
            logger.info("Running ask-user pipeline...")

            self.event = event
            # Chat history is only needed when generating a question, in a quiz-finished message,
            # or in a build-with-points message (to detect the language to use) - i.e. whenever
            # there is no event, or the event is BUILD_WITH_POINTS. For event "FIRST_QUESTION" no
            # chat history is needed.
            self.chat_history_needed = (
                self.event == "BUILD_WITH_POINTS" or not self.event
            )

            # Delegate to parent class for standardized execution
            local = dto.settings is not None and dto.settings.is_local()
            super().__call__(dto, variant, callback, local=local)

        except Exception as e:
            logger.error("Error in ask-user pipeline", exc_info=e)
            callback.fail("An error occurred while running the ask-user pipeline.")
