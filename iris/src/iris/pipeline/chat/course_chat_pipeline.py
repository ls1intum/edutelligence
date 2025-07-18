import json
import logging
import traceback
from datetime import datetime
from typing import Any, Callable, List, Optional

import pytz
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable
from weaviate.collections.classes.filters import Filter

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
from ...domain import CourseChatPipelineExecutionDTO, FeatureDTO
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.data.metrics.competency_jol_dto import CompetencyJolDTO
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ...llm.external.model import LanguageModel
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_unit_schema import LectureUnitSchema
from ...web.status.status_update import (
    CourseChatStatusCallback,
)
from ..pipeline import Pipeline
from ..prompts.iris_course_chat_prompts import (
    iris_base_system_prompt,
    iris_begin_agent_jol_prompt,
    iris_begin_agent_suffix_prompt,
    iris_chat_history_exists_begin_agent_prompt,
    iris_chat_history_exists_prompt,
    iris_competency_block,
    iris_course_meta_block,
    iris_examples_general_block,
    iris_examples_metrics_block,
    iris_exercise_block,
    iris_faq_block,
    iris_lecture_block,
    iris_no_chat_history_prompt_no_metrics_begin_agent_prompt,
    iris_no_chat_history_prompt_with_metrics_begin_agent_prompt,
    iris_no_competency_block_prompt,
    iris_no_exercise_block_prompt,
    iris_no_faq_block_prompt,
    iris_no_lecture_block_prompt,
)
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import (
    filter_variants_by_available_models,
    format_custom_instructions,
    generate_structured_tools_from_functions,
)
from .interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)
from .lecture_chat_pipeline import LectureChatPipeline

logger = logging.getLogger(__name__)


def get_mastery(progress, confidence):
    """
    Calculates a user's mastery level for competency given the progress.

    :param competency_progress: The user's progress
    :return: The mastery level
    """

    return min(100, max(0, round(progress * confidence)))


class CourseChatPipeline(Pipeline):
    """Course chat pipeline that answers course related questions from students."""

    llm: IrisLangchainChatModel
    llm_small: IrisLangchainChatModel
    pipeline: Runnable
    lecture_pipeline: LectureChatPipeline
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

        # Create the pipeline
        self.pipeline = self.llm | JsonOutputParser()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Course Chat Pipeline")
    def __call__(self, dto: CourseChatPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline
            :param dto: The pipeline execution data transfer object
            :param kwargs: The keyword arguments
        """

        # Cache results of tool allowance checks
        allow_lecture_tool = self.should_allow_lecture_tool(dto.course.id)
        allow_faq_tool = should_allow_faq_tool(self.db, dto.course.id)

        # Construct the base system prompt
        system_prompt_parts = [
            iris_base_system_prompt.replace(
                "{current_date}",
                datetime.now(tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )
        ]

        # Conditionally add modular blocks based on data availability
        system_prompt_parts.append(iris_course_meta_block)

        if dto.course.competencies:
            system_prompt_parts.append(iris_competency_block)
        else:
            system_prompt_parts.append(iris_no_competency_block_prompt)

        if dto.course.exercises:
            system_prompt_parts.append(iris_exercise_block)
        else:
            system_prompt_parts.append(iris_no_exercise_block_prompt)

        if allow_lecture_tool:
            system_prompt_parts.append(iris_lecture_block)
        else:
            system_prompt_parts.append(iris_no_lecture_block_prompt)

        if allow_faq_tool:
            system_prompt_parts.append(iris_faq_block)
        else:
            system_prompt_parts.append(iris_no_faq_block_prompt)

        # Conditionally add example blocks
        metrics_enabled = (
            dto.metrics
            and dto.course.competencies
            and dto.course.student_analytics_dashboard_enabled
        )
        if metrics_enabled:
            system_prompt_parts.append(iris_examples_metrics_block)
        else:
            system_prompt_parts.append(iris_examples_general_block)

        initial_prompt_main_block = "\n".join(system_prompt_parts)
        custom_instructions_formatted = format_custom_instructions(
            dto.custom_instructions
        )
        messages_for_template: list = []
        params: dict = {}
        agent_specific_primary_instruction = ""
        system_message_parts = [initial_prompt_main_block]

        # Storage for shared data between tools and pipeline
        lecture_content_storage: dict[str, Any] = {}
        faq_storage: dict[str, Any] = {}

        try:
            logger.info("Running course chat pipeline...")
            history: List[PyrisMessage] = dto.chat_history[-15:] or []
            # The actual Langchain history messages will be prepared later if needed
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

            if self.event == "jol":
                event_payload = CompetencyJolDTO.model_validate(dto.event_payload.event)
                comp = next(
                    (
                        c
                        for c in dto.course.competencies
                        if c.id == event_payload.competency_id
                    ),
                    None,
                )
                params["jol"] = json.dumps(
                    {
                        "value": event_payload.jol_value,
                        "competency_mastery": get_mastery(
                            event_payload.competency_progress,
                            event_payload.competency_confidence,
                        ),
                    }
                )
                params["competency"] = comp.model_dump_json() if comp else "{}"
                params["course_name"] = (
                    dto.course.name if dto.course and dto.course.name else "the course"
                )

                agent_specific_primary_instruction = iris_begin_agent_jol_prompt
                if (
                    history
                ):  # JOL can happen with or without prior history in this session
                    system_message_parts.append(iris_chat_history_exists_prompt)

            elif query is not None:  # Chat history exists and it's student's turn
                params["course_name"] = (
                    dto.course.name if dto.course and dto.course.name else "the course"
                )
                agent_specific_primary_instruction = (
                    iris_chat_history_exists_begin_agent_prompt
                )
                # iris_chat_history_exists_prompt is vital here
                system_message_parts.append(iris_chat_history_exists_prompt)

            else:  # No query, no JOL -> initial interaction from Iris
                params["course_name"] = (
                    dto.course.name if dto.course and dto.course.name else "the course"
                )
                if metrics_enabled:
                    agent_specific_primary_instruction = (
                        iris_no_chat_history_prompt_with_metrics_begin_agent_prompt
                    )
                else:
                    agent_specific_primary_instruction = (
                        iris_no_chat_history_prompt_no_metrics_begin_agent_prompt
                    )
                # No iris_chat_history_exists_prompt here as history is empty / not relevant for initiation

            # Create tools using builder functions
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

            system_message_parts.append(agent_specific_primary_instruction)
            system_message_parts.append(iris_begin_agent_suffix_prompt)
            if custom_instructions_formatted:
                system_message_parts.append(custom_instructions_formatted)

            final_system_content = "\n".join(
                filter(None, system_message_parts)
            )  # filter(None,...) to remove potential empty strings if a part is empty
            messages_for_template.append(SystemMessage(content=final_system_content))

            if chat_history_lc_messages:  # Only add history if it exists
                messages_for_template.extend(chat_history_lc_messages)

            messages_for_template.append(("placeholder", "{agent_scratchpad}"))
            self.prompt = ChatPromptTemplate.from_messages(messages_for_template)

            tools = generate_structured_tools_from_functions(tool_list)
            agent = create_tool_calling_agent(
                llm=self.llm, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

            out = None
            self.callback.in_progress()
            for step in agent_executor.iter(params):
                logger.debug("STEP: %s", step)
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_CHAT_COURSE_MESSAGE
                )
                if step.get("output", None):
                    out = step["output"]

            if lecture_content_storage.get("content"):
                self.callback.in_progress("Augmenting response ...")
                out = self.citation_pipeline(
                    lecture_content_storage["content"],
                    out,
                    InformationType.PARAGRAPHS,
                    variant=self.variant,
                    base_url=dto.settings.artemis_base_url,
                )
            self.tokens.extend(self.citation_pipeline.tokens)

            if faq_storage.get("faqs"):
                self.callback.in_progress("Augmenting response ...")
                out = self.citation_pipeline(
                    faq_storage["faqs"],
                    out,
                    InformationType.FAQS,
                    variant=self.variant,
                    base_url=dto.settings.artemis_base_url,
                )
            self.callback.done("Response created", final_result=out, tokens=self.tokens)

            try:
                self.callback.skip("Skipping suggestion generation.")
                if out:
                    suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                    suggestion_dto.chat_history = dto.chat_history
                    suggestion_dto.last_message = out
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
        except Exception as e:
            logger.error(
                "An error occurred while running the course chat pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            self.callback.error(
                "An error occurred while running the course chat pipeline.",
                tokens=self.tokens,
            )

    def should_allow_lecture_tool(self, course_id: int) -> bool:
        """
        Checks if there are indexed lectures for the given course

        :param course_id: The course ID
        :return: True if there are indexed lectures for the course, False otherwise
        """
        if not course_id:
            return False
        # Fetch the first object that matches the course ID with the language property
        result = self.db.lecture_units.query.fetch_objects(
            filters=Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                course_id
            ),
            limit=1,
            return_properties=[
                LectureUnitSchema.COURSE_NAME.value
            ],  # Requesting a minimal property
        )
        return len(result.objects) > 0

    @classmethod
    def get_variants(cls, available_llms: List[LanguageModel]) -> List[FeatureDTO]:
        variant_specs = [
            (
                ["gpt-4.1-mini"],
                FeatureDTO(
                    id="default",
                    name="Default",
                    description="Uses a smaller model for faster and cost-efficient responses.",
                ),
            ),
            (
                ["gpt-4.1", "gpt-4.1-mini"],
                FeatureDTO(
                    id="advanced",
                    name="Advanced",
                    description="Uses a larger chat model, balancing speed and quality.",
                ),
            ),
        ]

        return filter_variants_by_available_models(
            available_llms, variant_specs, pipeline_name="CourseChatPipeline"
        )
