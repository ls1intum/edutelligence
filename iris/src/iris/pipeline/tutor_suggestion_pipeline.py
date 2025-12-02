import json
import logging
import os
import traceback
from datetime import datetime
from typing import Any, Callable, List, cast

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from langsmith import traceable

from iris.common.pyris_message import IrisMessageRole
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.domain.data.post_dto import PostDTO
from iris.domain.variant.tutor_suggestion_variant import TutorSuggestionVariant
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
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
    create_tool_get_example_solution,
    create_tool_get_feedbacks,
    create_tool_get_last_artifact,
    create_tool_get_problem_statement,
    create_tool_get_simple_course_details,
    create_tool_get_submission_details,
    create_tool_lecture_content_retrieval,
    create_tool_repository_files,
)
from iris.web.status.status_update import TutorSuggestionCallback

logger = logging.getLogger(__name__)


class TutorSuggestionPipeline(
    AbstractAgentPipeline[
        CommunicationTutorSuggestionPipelineExecutionDTO, TutorSuggestionVariant
    ]
):
    """
    The TutorSuggestionPipeline creates a tutor suggestion when called.
    It uses the post received as an argument to create a suggestion based on the conversation
    """

    def __init__(self):
        super().__init__(implementation_id="tutor_suggestion_pipeline")
        self.lecture_retriever = None
        self.faq_retriever = None

        template_dir = os.path.join(os.path.dirname(__file__), "prompts", "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "tutor_suggestion_chat_system_prompt.j2"
        )

        self.tokens = []

    def __str__(self):
        return f"{self.__class__.__name__}"

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            CommunicationTutorSuggestionPipelineExecutionDTO, TutorSuggestionVariant
        ],
    ) -> list[Callable]:
        allow_lecture_tools = should_allow_lecture_tool(state.db, state.dto.course.id)
        allow_faq_tool = should_allow_faq_tool(state.db, state.dto.course.id)
        is_programming_exercise = state.dto.programming_exercise is not None
        is_text_exercise = state.dto.text_exercise is not None

        if not hasattr(state, "lecture_content_storage"):
            setattr(state, "lecture_content_storage", {})
        if not hasattr(state, "faq_storage"):
            setattr(state, "faq_storage", {})

        callback = state.callback
        if not isinstance(callback, TutorSuggestionCallback):
            callback = cast(TutorSuggestionCallback, state.callback)
        discussion = self._get_post_discussion(state.dto.post)

        tool_list: List[Callable] = []
        if is_programming_exercise:
            programming_exercise_tools: list[Callable] = [
                create_tool_get_additional_exercise_details(
                    state.dto.programming_exercise, callback
                ),
            ]
            if state.dto.submission is not None:
                submission = state.dto.submission
                programming_exercise_tools.extend(
                    [
                        create_tool_get_submission_details(submission, callback),
                        create_tool_get_build_logs_analysis(submission, callback),
                        create_tool_get_feedbacks(submission, callback),
                        create_tool_repository_files(submission.repository, callback),
                        create_tool_file_lookup(submission.repository, callback),
                        create_tool_get_problem_statement(
                            state.dto.programming_exercise, state.callback
                        ),
                    ]
                )
            tool_list.extend(programming_exercise_tools)

        if is_text_exercise:
            text_exercise_tools = [
                create_tool_get_problem_statement(
                    state.dto.text_exercise, state.callback
                ),
                create_tool_get_example_solution(
                    state.dto.text_exercise, state.callback
                ),
            ]
            tool_list.extend(text_exercise_tools)
        query_text = self._generate_retrieval_query_text(
            discussion,
            self.get_text_of_latest_user_message(state),
        )

        if len(state.dto.chat_history) > 0:
            tool_list.append(
                create_tool_get_last_artifact(state.dto.chat_history, callback)
            )
        if allow_lecture_tools:
            self.lecture_retriever = LectureRetrieval(state.db.client, local=state.dto.settings.artemis_llm_selection == "LOCAL_AI")
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
            self.faq_retriever = FaqRetrieval(state.db.client, local=state.dto.settings.artemis_llm_selection == "LOCAL_AI")
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
            CommunicationTutorSuggestionPipelineExecutionDTO, TutorSuggestionVariant
        ],
    ) -> str:
        allow_lecture_tool = should_allow_lecture_tool(state.db, state.dto.course.id)
        allow_faq_tool = should_allow_faq_tool(state.db, state.dto.course.id)
        is_programming_exercise = state.dto.programming_exercise is not None
        is_text_exercise = state.dto.text_exercise is not None
        tutor_query = self.get_text_of_latest_user_message(state) != ""
        discussion = self._get_post_discussion(state.dto.post)
        regeneration_requested = self.is_regeneration_by_user_requested(state)
        template_context = {
            "current_date": datetime.now(tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "allow_lecture_tool": allow_lecture_tool,
            "allow_faq_tool": allow_faq_tool,
            "has_chat_history": bool(state.message_history),
            "is_programming_exercise": is_programming_exercise,
            "is_text_exercise": is_text_exercise,
            "tutor_query": tutor_query,
            "discussion": discussion,
            "course_name": (
                state.dto.course.name
                if state.dto.course and state.dto.course.name
                else "the course"
            ),
            "regeneration_requested": regeneration_requested,
        }
        complete_system_prompt = self.system_prompt_template.render(template_context)
        logger.info(complete_system_prompt)
        return complete_system_prompt

    def get_agent_params(
        self,
        state: AgentPipelineExecutionState[
            CommunicationTutorSuggestionPipelineExecutionDTO, TutorSuggestionVariant
        ],
    ) -> dict[str, Any]:
        """
        Return the parameter dict passed to the agent executor.

        Returns:
            dict[str, Any]: Parameters for the agent executor
        """
        return {}

    def get_memiris_tenant(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO
    ) -> str:
        """
        Return the Memiris tenant identifier for the current user.

        Returns:
            str: The tenant identifier
        """
        return ""

    def get_memiris_reference(
        self, dto: CommunicationTutorSuggestionPipelineExecutionDTO
    ) -> str:
        """
        Does not return any reference, as memory creation is permanently disabled for this pipeline.

        Returns:
            str: "unknown"
        """
        return "unknown"

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[
            CommunicationTutorSuggestionPipelineExecutionDTO, TutorSuggestionVariant
        ],
    ) -> bool:
        return False

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            CommunicationTutorSuggestionPipelineExecutionDTO, TutorSuggestionVariant
        ],
    ) -> str:
        raw = state.result
        result_text = None
        suggestions = ""
        # Extract the textual suggestion robustly whether the agent returned a dict or a JSON string
        if isinstance(raw, dict):
            suggestions = raw.get("suggestions") or None
            result_text = raw.get("reply") or None
        elif isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                suggestions = parsed.get("suggestions", raw)
                result_text = (
                    parsed.get("reply")
                    if isinstance(parsed, dict) and "reply" in parsed
                    else None
                )
            except Exception:
                result_text = None
                suggestions = raw
        artifact_text = (
            suggestions
            if isinstance(suggestions, str) and suggestions.strip()
            else (
                json.dumps(suggestions, ensure_ascii=False)
                if suggestions
                else "No suggestions generated, please try again."
            )
        )
        state.callback.done(
            "Response generated",
            final_result=result_text,
            tokens=self.tokens,
            artifact=artifact_text,
        )
        return ""

    def _get_post_discussion(self, post: PostDTO) -> str:
        """
        Get the discussion of the post.
        Use this if you want to provide additional context regarding the discussion of a post.
        The discussion is a summary of the answers to the post.

        Returns:
            str: The discussion of the post.
        """
        if post and post.content:
            discussion = f"The posts question is: {post.content} by a user with id {post.user_id}\n"
            if post.answers:
                discussion += "The discussion of the post is:\n"
                for answer in post.answers:
                    if answer.content:
                        discussion += f"- {answer.content} by {answer.user_id}\n"
            else:
                discussion += "No answers to the post yet."
        else:
            discussion = "No post content available."

        return discussion

    def is_regeneration_by_user_requested(
        self,
        state: AgentPipelineExecutionState[
            CommunicationTutorSuggestionPipelineExecutionDTO, TutorSuggestionVariant
        ],
    ) -> bool:
        """
        Check if the user has requested a regeneration of the tutor suggestion.

        Args:
            state (AgentPipelineExecutionState): The current state of the pipeline execution.

        Returns:
            bool: True if regeneration is requested, False otherwise.
        """
        return (
            len(state.message_history) > 0
            and state.message_history[-1].sender == IrisMessageRole.ARTIFACT
        )

    def _generate_retrieval_query_text(
        self,
        discussion: str,
        user_query: str,
    ) -> str:
        """
        Generate the query text for the retrieval tools based on the discussion and user query.

        Args:
            discussion (str): The discussion of the post.
            user_query (str): The latest user message.

        Returns:
            str: The generated query text.
        """
        query = f"Find me relevant contents for the following discussion: {discussion}"
        if user_query:
            query += f"The user also asked specifically for: {user_query}"
        return query

    @traceable(name="Tutor Suggestion Pipeline")
    def __call__(
        self,
        dto: CommunicationTutorSuggestionPipelineExecutionDTO,
        variant: TutorSuggestionVariant,
        callback: TutorSuggestionCallback,
    ):
        """
        Run the pipeline.
        :param dto: execution data transfer object
        """
        try:
            logger.info("Running tutor suggestion pipeline...")

            super().__call__(dto, variant, callback, local=dto.settings.artemis_llm_selection == "LOCAL_AI")
        except Exception as e:
            logger.error(
                "An error occurred while running the tutor suggestion pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            callback.error(
                "An error occurred while running the tutor suggestion pipeline.",
                tokens=self.tokens,
            )

    @classmethod
    def get_variants(cls) -> List[TutorSuggestionVariant]:
        """
        Returns available variants for the TutorSuggestionPipeline.

        Returns:
            List of TutorSuggestionVariant objects representing available variants
        """
        return [
            TutorSuggestionVariant(
                variant_id="default",
                name="Default",
                description="Default tutor suggestion variant using the OpenAI GPT-OSS 20B model.",
                cloud_agent_model="gpt-oss:20b",
                local_agent_model="gpt-oss:20b",
            ),
            TutorSuggestionVariant(
                variant_id="advanced",
                name="Advanced",
                description="Advanced tutor suggestion variant using the OpenAI GPT-OSS 120B model.",
                cloud_agent_model="gpt-oss:120b",
                local_agent_model="gpt-oss:120b",
            ),
        ]
