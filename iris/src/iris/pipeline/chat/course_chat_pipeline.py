import json
import logging
import os
import traceback
from datetime import datetime
from typing import Any, Callable, List, Optional

import pytz
from jinja2 import Environment, FileSystemLoader
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import SystemMessage
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langsmith import traceable
from memiris.domain.memory import Memory

from ...common.mastery_utils import get_mastery
from ...common.memiris_setup import MemirisWrapper, get_tenant_for_user
from ...common.message_converters import (
    convert_iris_message_to_langchain_message,
)
from ...common.pipeline_enum import PipelineEnum
from ...common.pyris_message import PyrisMessage
from ...common.tools import (
    create_tool_faq_content_retrieval,
    create_tool_get_competency_list,
    create_tool_get_course_details,
    create_tool_get_exercise_list,
    create_tool_get_exercise_problem_statement,
    create_tool_get_student_exercise_metrics,
    create_tool_lecture_content_retrieval,
)
from ...domain import CourseChatPipelineExecutionDTO
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...domain.variant.course_chat_variant import CourseChatVariant
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ...llm.external.model import LanguageModel
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...retrieval.lecture.lecture_retrieval_utils import should_allow_lecture_tool
from ...vector_database.database import VectorDatabase
from ...web.status.status_update import (
    CourseChatStatusCallback,
)
from ..pipeline import Pipeline
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import (
    filter_variants_by_available_models,
    format_custom_instructions,
    generate_structured_tools_from_functions,
)
from .interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)

logger = logging.getLogger(__name__)


class CourseChatPipeline(Pipeline[CourseChatVariant]):
    """Course chat pipeline that answers course related questions from students."""

    llm: IrisLangchainChatModel
    suggestion_pipeline: InteractionSuggestionPipeline
    citation_pipeline: CitationPipeline
    callback: CourseChatStatusCallback
    prompt: ChatPromptTemplate
    variant: str
    event: str | None

    def __init__(
        self,
        callback: CourseChatStatusCallback,
        variant: str = "default",
        event: str | None = None,
    ):
        super().__init__(implementation_id="course_chat_pipeline")

        self.variant = variant
        self.event = event

        # Set the langchain chat model
        completion_args = CompletionArguments(temperature=0.5, max_tokens=2000)

        if variant == "advanced":
            model = "gpt-4.1"
        else:
            model = "gpt-4.1-mini"

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model),
            completion_args=completion_args,
        )

        self.callback = callback

        self.db = VectorDatabase()
        self.lecture_retriever = LectureRetrieval(self.db.client)
        self.faq_retriever = FaqRetrieval(self.db.client)
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant="course")
        self.citation_pipeline = CitationPipeline()

        # Setup Jinja2 template environment
        template_dir = os.path.join(
            os.path.dirname(__file__), "..", "prompts", "templates"
        )
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))
        self.system_prompt_template = self.jinja_env.get_template(
            "course_chat_system_prompt.j2"
        )

        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def _build_system_prompt(
        self,
        dto: CourseChatPipelineExecutionDTO,
        allow_lecture_tool: bool = True,
        allow_faq_tool: bool = True,
        allow_memiris_tool: bool = True,
        has_chat_history: bool = False,
        custom_instructions: str = "",
    ) -> tuple[str, bool]:
        """
        Build the complete system prompt using Jinja2 template.

        Args:
            dto (CourseChatPipelineExecutionDTO): The pipeline execution DTO.
            allow_lecture_tool (bool): Whether lecture tool is available.
            allow_faq_tool (bool): Whether FAQ tool is available.
            allow_memiris_tool (bool): Whether Memiris tool is available.
            has_chat_history (bool): Whether there is chat history.
            custom_instructions (str): Custom instructions to append.

        Returns:
            tuple[str, bool]: (complete_system_prompt, metrics_enabled)
        """
        # Determine metrics availability
        metrics_enabled = (
            dto.metrics
            and dto.course.competencies
            and dto.course.student_analytics_dashboard_enabled
        )

        # Prepare template context
        template_context = {
            "current_date": datetime.now(tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
            "has_competencies": bool(dto.course.competencies),
            "has_exercises": bool(dto.course.exercises),
            "allow_lecture_tool": allow_lecture_tool,
            "allow_faq_tool": allow_faq_tool,
            "allow_memiris_tool": allow_memiris_tool,
            "metrics_enabled": metrics_enabled,
            "has_chat_history": has_chat_history,
            "event": self.event,
            "custom_instructions": custom_instructions,
            "course_name": (
                dto.course.name if dto.course and dto.course.name else "the course"
            ),
        }

        # Handle JOL event specific data
        if self.event == "jol" and dto.event_payload:
            from ...domain.data.metrics.competency_jol_dto import CompetencyJolDTO

            event_payload = CompetencyJolDTO.model_validate(dto.event_payload.event)
            comp = next(
                (
                    c
                    for c in dto.course.competencies
                    if c.id == event_payload.competency_id
                ),
                None,
            )
            template_context["jol"] = json.dumps(
                {
                    "value": event_payload.jol_value,
                    "competency_mastery": get_mastery(
                        event_payload.competency_progress,
                        event_payload.competency_confidence,
                    ),
                }
            )
            template_context["competency"] = comp.model_dump_json() if comp else "{}"

        # Render the complete system prompt
        complete_system_prompt = self.system_prompt_template.render(template_context)

        return complete_system_prompt, metrics_enabled

    def _prepare_chat_context(
        self, dto: CourseChatPipelineExecutionDTO
    ) -> tuple[List[PyrisMessage], list, Optional[PyrisMessage], str]:
        """
        Prepare chat context by processing history and extracting query information.

        Args:
            dto (CourseChatPipelineExecutionDTO): The pipeline execution DTO.

        Returns:
            tuple: (history, chat_history_lc_messages, query, query_text)
        """
        history: List[PyrisMessage] = dto.chat_history[-15:] or []
        chat_history_lc_messages = []
        if history:
            chat_history_lc_messages = [
                convert_iris_message_to_langchain_message(message)
                for message in history
            ]

        query: Optional[PyrisMessage] = (
            dto.chat_history[-1] if dto.chat_history else None
        )
        query_text = (
            query.contents[0].text_content
            if query
            and query.contents
            and isinstance(query.contents[0], TextMessageContentDTO)
            else ""
        )

        return history, chat_history_lc_messages, query, query_text

    def _create_tools(
        self,
        dto: CourseChatPipelineExecutionDTO,
        allow_lecture_tool: bool,
        allow_faq_tool: bool,
        allow_memiris_tool: bool,
        query_text: str,
        history: List[PyrisMessage],
        lecture_content_storage: dict[str, Any],
        faq_storage: dict[str, Any],
        accessed_memory_storage: list[Memory],
    ) -> list[Callable]:
        """
        Create and configure the tools for the agent.

        Args:
            dto (CourseChatPipelineExecutionDTO): The pipeline execution DTO.
            allow_lecture_tool (bool): Whether lecture tool is available.
            allow_faq_tool (bool): Whether FAQ tool is available.
            allow_memiris_tool (bool): Whether Memiris tools are available.
            query_text (str): The extracted query text.
            history (List[PyrisMessage]): Chat history messages.
            lecture_content_storage (dict[str, Any]): Storage for lecture content.
            faq_storage (dict[str, Any]): Storage for FAQ content.

        Returns:
            list[Callable]: List of configured tools.
        """
        tool_list: list[Callable] = [
            create_tool_get_course_details(dto, self.callback),
        ]

        if dto.course.exercises:
            tool_list.append(create_tool_get_exercise_list(dto, self.callback))
            tool_list.append(
                create_tool_get_exercise_problem_statement(dto, self.callback)
            )

        if dto.metrics and dto.metrics.exercise_metrics and dto.course.exercises:
            tool_list.append(
                create_tool_get_student_exercise_metrics(dto, self.callback)
            )

        if dto.course.competencies and len(dto.course.competencies) > 0:
            tool_list.append(create_tool_get_competency_list(dto, self.callback))

        if allow_lecture_tool:
            tool_list.append(
                create_tool_lecture_content_retrieval(
                    self.lecture_retriever,
                    dto,
                    self.callback,
                    query_text,
                    history,
                    lecture_content_storage,
                )
            )

        if allow_faq_tool:
            tool_list.append(
                create_tool_faq_content_retrieval(
                    self.faq_retriever,
                    dto,
                    self.callback,
                    query_text,
                    history,
                    faq_storage,
                )
            )

        if allow_memiris_tool:
            tool_list.append(
                self.memiris_wrapper.create_tool_memory_search(accessed_memory_storage)
            )
            tool_list.append(
                self.memiris_wrapper.create_tool_find_similar_memories(
                    accessed_memory_storage
                )
            )

        return tool_list

    def _build_prompt_and_agent(
        self,
        complete_system_prompt: str,
        chat_history_lc_messages: list,
        tool_list: list[Callable],
    ) -> tuple[AgentExecutor, ChatPromptTemplate]:
        """
        Build the prompt template and create the agent executor.

        Args:
            complete_system_prompt (str): Complete system prompt from Jinja2.
            chat_history_lc_messages (list): LangChain chat history messages.
            tool_list (list[Callable]): List of available tools.

        Returns:
            tuple: (agent_executor, prompt)
        """
        # Create a single system message with the complete prompt
        messages_for_template = [SystemMessage(content=complete_system_prompt)]

        if chat_history_lc_messages:  # Only add history if it exists
            messages_for_template.extend(chat_history_lc_messages)

        messages_for_template.append(("placeholder", "{agent_scratchpad}"))
        prompt = ChatPromptTemplate.from_messages(messages_for_template)

        tools = generate_structured_tools_from_functions(tool_list)
        agent = create_tool_calling_agent(llm=self.llm, tools=tools, prompt=prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

        return agent_executor, prompt

    def _execute_agent(self, agent_executor: AgentExecutor) -> Optional[str]:
        """
        Execute the agent and collect the output.

        Args:
            agent_executor (AgentExecutor): The configured agent executor.

        Returns:
            Optional[str]: The agent's output.
        """
        out = None
        self.callback.in_progress()
        for step in agent_executor.iter({}):
            logger.debug("STEP: %s", step)
            self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_CHAT_COURSE_MESSAGE)
            if step.get("output", None):
                out = step["output"]
        return out

    def _process_citations(
        self,
        output: str,
        lecture_content_storage: dict[str, Any],
        faq_storage: dict[str, Any],
        dto: CourseChatPipelineExecutionDTO,
    ) -> str:
        """
        Process citations for lecture content and FAQs.

        Args:
            output (str): The agent's output.
            lecture_content_storage (dict[str, Any]): Storage for lecture content.
            faq_storage (dict[str, Any]): Storage for FAQ content.
            dto (CourseChatPipelineExecutionDTO): The pipeline execution DTO.

        Returns:
            str: The output with citations added.
        """
        if lecture_content_storage.get("content"):
            self.callback.in_progress("Augmenting response ...")
            output = self.citation_pipeline(
                lecture_content_storage["content"],
                output,
                InformationType.PARAGRAPHS,
                variant=self.variant,
                base_url=dto.settings.artemis_base_url,
            )
        self.tokens.extend(self.citation_pipeline.tokens)

        if faq_storage.get("faqs"):
            self.callback.in_progress("Augmenting response ...")
            output = self.citation_pipeline(
                faq_storage["faqs"],
                output,
                InformationType.FAQS,
                variant=self.variant,
                base_url=dto.settings.artemis_base_url,
            )

        return output

    def _generate_suggestions(
        self, output: str, dto: CourseChatPipelineExecutionDTO
    ) -> None:
        """
        Generate interaction suggestions based on the output.

        Args:
            output (str): The agent's output.
            dto (CourseChatPipelineExecutionDTO): The pipeline execution DTO.
        """
        try:
            self.callback.in_progress("Generating interaction suggestions...")
            if output:
                suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                suggestion_dto.chat_history = dto.chat_history
                suggestion_dto.last_message = output
                suggestions = self.suggestion_pipeline(suggestion_dto)
                self.callback.done(final_result=None, suggestions=suggestions)
            else:
                # This should never happen but whatever
                self.callback.skip(
                    "Skipping suggestion generation as no output was generated."
                )
        except Exception as e:
            logger.error(
                "An error occurred while running the course chat interaction suggestion pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            self.callback.error("Generating interaction suggestions failed.")

    @traceable(name="Course Chat Pipeline")
    def __call__(self, dto: CourseChatPipelineExecutionDTO, **kwargs):
        """
        Run the course chat pipeline.

        Args:
            dto (CourseChatPipelineExecutionDTO): The pipeline execution data transfer object.
            **kwargs: Additional keyword arguments.
        """
        self.memiris_wrapper = MemirisWrapper(
            self.db.client, get_tenant_for_user(dto.user.id)
        )
        allow_lecture_tool = should_allow_lecture_tool(self.db, dto.course.id)
        allow_faq_tool = should_allow_faq_tool(self.db, dto.course.id)
        allow_memiris_tool = bool(
            dto.user.memiris_enabled and self.memiris_wrapper.has_memories()
        )

        # Storage for shared data between tools and pipeline
        lecture_content_storage: dict[str, Any] = {}
        faq_storage: dict[str, Any] = {}
        accessed_memory_storage: list[Memory] = []
        memory_creation_storage: list[Memory] = []

        try:
            logger.info("Running course chat pipeline...")

            # Prepare chat context
            history, chat_history_lc_messages, query, query_text = (
                self._prepare_chat_context(dto)
            )

            # Format custom instructions
            custom_instructions_formatted = format_custom_instructions(
                dto.custom_instructions
            )

            # Build complete system prompt using Jinja2
            complete_system_prompt, _ = self._build_system_prompt(
                dto,
                allow_lecture_tool,
                allow_faq_tool,
                allow_memiris_tool,
                has_chat_history=bool(history),
                custom_instructions=custom_instructions_formatted,
            )

            # Start memory creation in a separate thread
            if dto.user.memiris_enabled:
                memory_creation_thread = (
                    self.memiris_wrapper.create_memories_in_separate_thread(
                        query_text, memory_creation_storage
                    )
                )

            # Create tools
            tool_list = self._create_tools(
                dto,
                allow_lecture_tool,
                allow_faq_tool,
                allow_memiris_tool,
                query_text,
                history,
                lecture_content_storage,
                faq_storage,
                accessed_memory_storage,
            )

            # Build prompt and agent
            agent_executor, self.prompt = self._build_prompt_and_agent(
                complete_system_prompt,
                chat_history_lc_messages,
                tool_list,
            )

            # Execute agent
            output = self._execute_agent(agent_executor)

            # Process citations
            output = self._process_citations(
                output, lecture_content_storage, faq_storage, dto
            )

            # Complete main process
            self.callback.done(
                "Response created",
                final_result=output,
                tokens=self.tokens,
                accessed_memories=accessed_memory_storage,
            )

            # Generate suggestions
            self._generate_suggestions(output, dto)

            # Wait for memory creation to finish
            if dto.user.memiris_enabled:
                self.callback.in_progress("Waiting for memory creation to finish ...")
                # noinspection PyUnboundLocalVariable
                memory_creation_thread.join()
                self.callback.done(
                    "Memory creation finished.",
                    created_memories=memory_creation_storage,
                )
            else:
                self.callback.skip(
                    "Memory creation is disabled.",
                )
        except Exception as e:
            # Only try to join the thread if it was created
            if "memory_creation_thread" in locals():
                memory_creation_thread.join(0.0000001)
            logger.error(
                "An error occurred while running the course chat pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            self.callback.error(
                "An error occurred while running the course chat pipeline.",
                tokens=self.tokens,
            )

    @classmethod
    def get_variants(cls) -> List[CourseChatVariant]:
        return [
            CourseChatVariant(
                id="default",
                name="Default",
                description="Uses a smaller model for faster and cost-efficient responses.",
                agent_model="gpt-4.1-mini",
                citation_model="gpt-4.1-mini",
            ),
            CourseChatVariant(
                id="advanced",
                name="Advanced",
                description="Uses a larger chat model, balancing speed and quality.",
                agent_model="gpt-4.1",
                citation_model="gpt-4.1-mini",
            ),
        ]
