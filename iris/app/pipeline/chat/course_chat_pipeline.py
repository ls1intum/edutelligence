import json
import logging
import traceback
import typing
from datetime import datetime
from typing import List, Optional, Union

import pytz
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable
from weaviate.collections.classes.filters import Filter

from .interaction_suggestion_pipeline import (
    InteractionSuggestionPipeline,
)
from .lecture_chat_pipeline import LectureChatPipeline
from ..shared.citation_pipeline import CitationPipeline
from ..shared.utils import generate_structured_tools_from_functions
from ...common.message_converters import convert_iris_message_to_langchain_message
from ...common.pyris_message import PyrisMessage
from ...domain.data.metrics.competency_jol_dto import CompetencyJolDTO
from ...llm import CapabilityRequestHandler, RequirementList
from ..prompts.iris_course_chat_prompts import (
    tell_iris_initial_system_prompt,
    tell_begin_agent_prompt,
    tell_chat_history_exists_prompt,
    tell_no_chat_history_prompt,
    tell_begin_agent_jol_prompt,
)
from ..prompts.iris_course_chat_prompts_elicit import (
    elicit_iris_initial_system_prompt,
    elicit_begin_agent_prompt,
    elicit_chat_history_exists_prompt,
    elicit_no_chat_history_prompt,
    elicit_begin_agent_jol_prompt,
)
from ...domain import CourseChatPipelineExecutionDTO
from app.common.PipelineEnum import PipelineEnum
from ...retrieval.lecture_retrieval import LectureRetrieval
from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_schema import LectureSchema
from ...web.status.status_update import (
    CourseChatStatusCallback,
)
from ...llm import CompletionArguments
from ...llm.langchain import IrisLangchainChatModel

from ..pipeline import Pipeline

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

    llm_big: IrisLangchainChatModel
    llm_small: IrisLangchainChatModel
    pipeline: Runnable
    lecture_pipeline: LectureChatPipeline
    suggestion_pipeline: InteractionSuggestionPipeline
    citation_pipeline: CitationPipeline
    callback: CourseChatStatusCallback
    prompt: ChatPromptTemplate
    variant: str
    event: str | None
    retrieved_paragraphs: List[dict] = None

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
        self.llm_big = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(
                    gpt_version_equivalent=4.5,
                )
            ),
            completion_args=completion_args,
        )
        self.llm_small = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(
                    gpt_version_equivalent=4.25,
                )
            ),
            completion_args=completion_args,
        )
        self.callback = callback

        self.db = VectorDatabase()
        self.retriever = LectureRetrieval(self.db.client)
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant="course")
        self.citation_pipeline = CitationPipeline()

        # Create the pipeline
        self.pipeline = self.llm_big | JsonOutputParser()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm_big={self.llm_big}, llm_small={self.llm_small})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm_big={self.llm_big}, llm_small={self.llm_small})"

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
            Retrieve content from indexed lecture slides.
            This will run a RAG retrieval based on the chat history on the indexed lecture slides and return the
            most relevant paragraphs.
            Use this if you think it can be useful to answer the student's question, or if the student explicitly asks
            a question about the lecture content or slides.
            Only use this once.
            """
            self.callback.in_progress("Retrieving lecture content ...")
            self.retrieved_paragraphs = self.retriever(
                chat_history=history,
                student_query=query.contents[0].text_content,
                result_limit=5,
                course_name=dto.course.name,
                course_id=dto.course.id,
                base_url=dto.settings.artemis_base_url,
            )

            result = ""
            for paragraph in self.retrieved_paragraphs:
                lct = "Lecture: {}, Unit: {}, Page: {}\nContent:\n---{}---\n\n".format(
                    paragraph.get(LectureSchema.LECTURE_NAME.value),
                    paragraph.get(LectureSchema.LECTURE_UNIT_NAME.value),
                    paragraph.get(LectureSchema.PAGE_NUMBER.value),
                    paragraph.get(LectureSchema.PAGE_TEXT_CONTENT.value),
                )
                result += lct
            return result

        if dto.user.id % 3 < 2:
            iris_initial_system_prompt = tell_iris_initial_system_prompt
            begin_agent_prompt = tell_begin_agent_prompt
            chat_history_exists_prompt = tell_chat_history_exists_prompt
            no_chat_history_prompt = tell_no_chat_history_prompt
            begin_agent_jol_prompt = tell_begin_agent_jol_prompt
        else:
            iris_initial_system_prompt = elicit_iris_initial_system_prompt
            begin_agent_prompt = elicit_begin_agent_prompt
            chat_history_exists_prompt = elicit_chat_history_exists_prompt
            no_chat_history_prompt = elicit_no_chat_history_prompt
            begin_agent_jol_prompt = elicit_begin_agent_jol_prompt

        try:
            logger.info("Running course chat pipeline...")
            history: List[PyrisMessage] = dto.chat_history[-5:] or []
            query: Optional[PyrisMessage] = (
                dto.chat_history[-1] if dto.chat_history else None
            )

            # Set up the initial prompt
            initial_prompt_with_date = iris_initial_system_prompt.replace(
                "{current_date}",
                datetime.now(tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )

            if self.event == "jol":
                event_payload = CompetencyJolDTO.model_validate(dto.event_payload.event)
                logger.debug(f"Event Payload: {event_payload}")
                comp = next(
                    (
                        c
                        for c in dto.course.competencies
                        if c.id == event_payload.competency_id
                    ),
                    None,
                )
                agent_prompt = begin_agent_jol_prompt
                params = {
                    "jol": json.dumps(
                        {
                            "value": event_payload.jol_value,
                            "competency_mastery": get_mastery(
                                event_payload.competency_progress,
                                event_payload.competency_confidence,
                            ),
                        }
                    ),
                    "competency": comp.model_dump_json(),
                }
            else:
                agent_prompt = (
                    begin_agent_prompt if query is not None else no_chat_history_prompt
                )
                params = {
                    "course_name": (
                        dto.course.name if dto.course else "<Unknown course name>"
                    ),
                }

            if query is not None:
                # Add the conversation to the prompt
                chat_history_messages = [
                    convert_iris_message_to_langchain_message(message)
                    for message in history
                ]
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        SystemMessage(
                            initial_prompt_with_date
                            + "\n"
                            + chat_history_exists_prompt
                            + "\n"
                            + agent_prompt
                        ),
                        *chat_history_messages,
                        ("placeholder", "{agent_scratchpad}"),
                    ]
                )
            else:
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        SystemMessage(
                            initial_prompt_with_date + "\n" + agent_prompt + "\n"
                        ),
                        ("placeholder", "{agent_scratchpad}"),
                    ]
                )

            tool_list = [
                get_course_details,
                get_exercise_list,
                get_student_exercise_metrics,
                get_competency_list,
            ]
            if self.should_allow_lecture_tool(dto.course.id):
                tool_list.append(lecture_content_retrieval)

            tools = generate_structured_tools_from_functions(tool_list)
            # No idea why we need this extra contrary to exercise chat agent in this case, but solves the issue.
            params.update({"tools": tools})
            agent = create_tool_calling_agent(
                llm=self.llm_big, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)

            out = None
            self.callback.in_progress()
            for step in agent_executor.iter(params):
                print("STEP:", step)
                self._append_tokens(
                    self.llm_big.tokens, PipelineEnum.IRIS_CHAT_COURSE_MESSAGE
                )
                if step.get("output", None):
                    out = step["output"]

            if self.retrieved_paragraphs:
                self.callback.in_progress("Augmenting response ...")
                out = self.citation_pipeline(self.retrieved_paragraphs, out)
            self.tokens.extend(self.citation_pipeline.tokens)

            self.callback.done("Response created", final_result=out, tokens=self.tokens)

            # try:
            #     self.callback.skip("Skipping suggestion generation.")
            # if out:
            #     suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
            #     suggestion_dto.chat_history = dto.chat_history
            #     suggestion_dto.last_message = out
            #     suggestions = self.suggestion_pipeline(suggestion_dto)
            #     self.callback.done(final_result=None, suggestions=suggestions)
            # else:
            #     # This should never happen but whatever
            #     self.callback.skip(
            #         "Skipping suggestion generation as no output was generated."
            #     )
            # except Exception as e:
            #     logger.error(
            #         "An error occurred while running the course chat interaction suggestion pipeline",
            #         exc_info=e,
            #     )
            #     traceback.print_exc()
            #     self.callback.error("Generating interaction suggestions failed.")
        except Exception as e:
            logger.error(
                "An error occurred while running the course chat pipeline", exc_info=e
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
        if course_id:
            # Fetch the first object that matches the course ID with the language property
            result = self.db.lectures.query.fetch_objects(
                filters=Filter.by_property(LectureSchema.COURSE_ID.value).equal(
                    course_id
                ),
                limit=1,
                return_properties=[LectureSchema.COURSE_NAME.value],
            )
            return len(result.objects) > 0
        return False


def datetime_to_string(dt: Optional[datetime]) -> str:
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
