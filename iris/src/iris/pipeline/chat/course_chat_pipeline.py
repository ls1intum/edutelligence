import json
import logging
import time
import traceback
import typing
from datetime import datetime
from typing import List, Optional, Union

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
from ...domain import CourseChatPipelineExecutionDTO, FeatureDTO
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.data.metrics.competency_jol_dto import CompetencyJolDTO
from ...domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
)
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ...llm.external.model import LanguageModel
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import format_faqs, should_allow_faq_tool
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
    lecture_content: LectureRetrievalDTO = None
    retrieved_faqs: List[dict] = None

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
            model = "gpt-4.1-nano"

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
        logger.debug(dto.model_dump_json(indent=4))

        # Define tools
        def get_exercise_list() -> list[dict]:
            """
            Get the list of exercises in the course.
            Use this if the student asks you about an exercise.
            Note: The exercise contains a list of submissions (timestamp and score) of this student so you
            can provide additional context regarding their progress and tendencies over time.
            Also, ensure to use the provided current date and time and compare it to the start date and due date etc.
            Do not recommend that the student should work on exercises with a past due date.
            The submissions array tells you about the status of the student in this exercise:
            You see when the student submitted the exercise and what score they got.
            A 100% score means the student solved the exercise correctly and completed it.
            """
            self.callback.in_progress("Reading exercise list ...")
            # for debug sleep a second
            time.sleep(1)
            current_time = datetime.now(tz=pytz.UTC)
            exercises = []
            for exercise in dto.course.exercises:
                exercise_dict = exercise.model_dump()
                exercise_dict["due_date_over"] = (
                    exercise.due_date < current_time if exercise.due_date else None
                )
                exercises.append(exercise_dict)
            return exercises

        def get_course_details() -> dict:
            """
            Get the following course details: course name, course description, programming language, course start date,
            and course end date.
            """
            self.callback.in_progress("Reading course details ...")
            return {
                "course_name": (
                    dto.course.name if dto.course else "No course provided"
                ),
                "course_description": (
                    dto.course.description
                    if dto.course and dto.course.description
                    else "No course description provided"
                ),
                "programming_language": (
                    dto.course.default_programming_language
                    if dto.course and dto.course.default_programming_language
                    else "No course provided"
                ),
                "course_start_date": (
                    datetime_to_string(dto.course.start_time)
                    if dto.course and dto.course.start_time
                    else "No start date provided"
                ),
                "course_end_date": (
                    datetime_to_string(dto.course.end_time)
                    if dto.course and dto.course.end_time
                    else "No end date provided"
                ),
            }

        def get_student_exercise_metrics(
            exercise_ids: typing.List[int],
        ) -> Union[dict[int, dict], str]:
            """
            Get the student exercise metrics for the given exercises.
            Important: You have to pass the correct exercise ids here. If you don't know it,
            check out the exercise list first and look up the id of the exercise you are interested in.
            UNDER NO CIRCUMSTANCES GUESS THE ID, such as 12345. Always use the correct ids.
            You must pass an array of IDs. It can be more than one.
            The following metrics are returned:
            - global_average_score: The average score of all students in the exercise.
            - score_of_student: The score of the student.
            - global_average_latest_submission: The average relative time of the latest
            submissions of all students in the exercise.
            - latest_submission_of_student: The relative time of the latest submission of the student.
            """
            self.callback.in_progress("Checking your statistics ...")
            if not dto.metrics or not dto.metrics.exercise_metrics:
                return "No data available!! Do not requery."
            metrics = dto.metrics.exercise_metrics
            if metrics.average_score and any(
                exercise_id in metrics.average_score for exercise_id in exercise_ids
            ):
                return {
                    exercise_id: {
                        "global_average_score": metrics.average_score[exercise_id],
                        "score_of_student": metrics.score.get(exercise_id, None),
                        "global_average_latest_submission": metrics.average_latest_submission.get(
                            exercise_id, None
                        ),
                        "latest_submission_of_student": metrics.latest_submission.get(
                            exercise_id, None
                        ),
                    }
                    for exercise_id in exercise_ids
                    if exercise_id in metrics.average_score
                }
            else:
                return "No data available! Do not requery."

        def get_competency_list() -> list:
            """
            Get the list of competencies in the course.
            Exercises might be associated with competencies. A competency is a skill or knowledge that a student
            should have after completing the course, and instructors may add lectures and exercises
            to these competencies.
            You can use this if the students asks you about a competency, or if you want to provide additional context
            regarding their progress overall or in a specific area.
            A competency has the following attributes: name, description, taxonomy, soft due date, optional,
            and mastery threshold.
            The response may include metrics for each competency, such as progress and mastery (0% - 100%).
            These are system-generated.
            The judgment of learning (JOL) values indicate the self-reported mastery by the student (0 - 5, 5 star).
            The object describing it also indicates the system-computed mastery at the time when the student
            added their JoL assessment.
            """
            self.callback.in_progress("Reading competency list ...")
            # for debug sleep a second
            time.sleep(1)
            if not dto.metrics or not dto.metrics.competency_metrics:
                return dto.course.competencies
            competency_metrics = dto.metrics.competency_metrics
            return [
                {
                    "info": competency_metrics.competency_information.get(comp, None),
                    "exercise_ids": competency_metrics.exercises.get(comp, []),
                    "progress": competency_metrics.progress.get(comp, 0),
                    "mastery": get_mastery(
                        competency_metrics.progress.get(comp, 0),
                        competency_metrics.confidence.get(comp, 0),
                    ),
                    "judgment_of_learning": (
                        competency_metrics.jol_values.get[comp].json()
                        if competency_metrics.jol_values
                        and comp in competency_metrics.jol_values
                        else None
                    ),
                }
                for comp in competency_metrics.competency_information
            ]

        def lecture_content_retrieval() -> str:
            """
            Retrieve content from indexed lecture content.
            This will run a RAG retrieval based on the chat history on the indexed lecture slides,
            the indexed lecture transcriptions and the indexed lecture segments,
            which are summaries of the lecture slide content and lecture transcription content from one slide a
            nd return the most relevant paragraphs.
            Use this if you think it can be useful to answer the student's question, or if the student explicitly asks
            a question about the lecture content or slides.
            Only use this once.
            """
            self.callback.in_progress("Retrieving lecture content ...")
            self.lecture_content = self.lecture_retriever(
                query=query.contents[0].text_content,
                course_id=dto.course.id,
                chat_history=history,
                lecture_id=None,
                lecture_unit_id=None,
                base_url=dto.settings.artemis_base_url,
            )

            result = "Lecture slide content:\n"
            for paragraph in self.lecture_content.lecture_unit_page_chunks:
                result += (
                    f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                    f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
                )

            result += "Lecture transcription content:\n"
            for paragraph in self.lecture_content.lecture_transcriptions:
                result += (
                    f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                    f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_text}---\n\n"
                )

            result += "Lecture segment content:\n"
            for paragraph in self.lecture_content.lecture_unit_segments:
                result += (
                    f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                    f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_summary}---\n\n"
                )

            return result

        def faq_content_retrieval() -> str:
            """
            Use this tool to retrieve information from indexed FAQs.
            It is suitable when no other tool fits, it is a common question or the question is frequently asked,
            or the question could be effectively answered by an FAQ. Also use this if the question is explicitly
            organizational and course-related. An organizational question about the course might be
            "What is the course structure?" or "How do I enroll?" or exam related content like "When is the exam".
            The tool performs a RAG retrieval based on the chat history to find the most relevant FAQs.
            Each FAQ follows this format: FAQ ID, FAQ Question, FAQ Answer.
            Respond to the query concisely and solely using the answer from the relevant FAQs.
            This tool should only be used once per query.
            """
            self.callback.in_progress("Retrieving faq content ...")
            self.retrieved_faqs = self.faq_retriever(
                chat_history=history,
                student_query=query.contents[0].text_content,
                result_limit=10,
                course_name=dto.course.name,
                course_id=dto.course.id,
                base_url=dto.settings.artemis_base_url,
            )

            result = format_faqs(self.retrieved_faqs)
            return result

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

            if self.event == "jol":
                event_payload = CompetencyJolDTO.model_validate(dto.event_payload.event)
                logger.debug("Event Payload: %s", event_payload)
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

            tool_list = [
                get_course_details,
                get_exercise_list,
                get_student_exercise_metrics,
                get_competency_list,
            ]
            if allow_lecture_tool:
                tool_list.append(lecture_content_retrieval)

            print("Allowing lecture tool:", allow_lecture_tool)

            if allow_faq_tool:
                tool_list.append(faq_content_retrieval)

            tools = generate_structured_tools_from_functions(tool_list)
            agent = create_tool_calling_agent(
                llm=self.llm, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

            out = None
            self.callback.in_progress()
            for step in agent_executor.iter(params):
                print("STEP:", step)
                self._append_tokens(
                    self.llm.tokens, PipelineEnum.IRIS_CHAT_COURSE_MESSAGE
                )
                if step.get("output", None):
                    out = step["output"]

            if self.lecture_content:
                self.callback.in_progress("Augmenting response ...")
                out = self.citation_pipeline(
                    self.lecture_content, out, InformationType.PARAGRAPHS
                )
            self.tokens.extend(self.citation_pipeline.tokens)

            if self.retrieved_faqs:
                self.callback.in_progress("Augmenting response ...")
                out = self.citation_pipeline(
                    self.retrieved_faqs,
                    out,
                    InformationType.FAQS,
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
                ["gpt-4.1-nano"],
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


def datetime_to_string(dt: Optional[datetime]) -> str:
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
