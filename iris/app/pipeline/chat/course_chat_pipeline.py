import json
import logging
import traceback
from datetime import datetime
from typing import List, Optional, Union

import pytz
from langchain.agents import create_structured_chat_agent, AgentExecutor
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    AIMessagePromptTemplate,
    MessagesPlaceholder,
)
from langchain_core.runnables import Runnable
from langchain_core.tools import tool

from .course_chat_interaction_suggestion_pipeline import (
    CourseInteractionSuggestionPipeline,
)
from ...common import convert_iris_message_to_langchain_message
from ...domain import PyrisMessage
from ...domain.chat.course_chat.course_chat_interaction_suggestion_dto import (
    CourseChatInteractionSuggestionPipelineExecutionDTO,
)
from ...domain.data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from ...llm import CapabilityRequestHandler, RequirementList
from ..prompts.iris_course_chat_prompts import (
    tell_iris_initial_system_prompt,
    tell_begin_agent_prompt,
    tell_chat_history_exists_prompt,
    tell_no_chat_history_prompt,
    tell_format_reminder_prompt,
    tell_begin_agent_jol_prompt,
)
from ..prompts.iris_course_chat_prompts_elicit import (
    elicit_iris_initial_system_prompt,
    elicit_begin_agent_prompt,
    elicit_chat_history_exists_prompt,
    elicit_no_chat_history_prompt,
    elicit_format_reminder_prompt,
    elicit_begin_agent_jol_prompt,
)
from ...domain import CourseChatPipelineExecutionDTO
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
    weight = 2.0 / 3.0
    return (1 - weight) * progress + weight * confidence


class CourseChatPipeline(Pipeline):
    """Course chat pipeline that answers course related questions from students."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: CourseChatStatusCallback
    prompt: ChatPromptTemplate
    variant: str

    def __init__(self, callback: CourseChatStatusCallback, variant: str = "default"):
        super().__init__(implementation_id="course_chat_pipeline")

        self.variant = variant

        # Set the langchain chat model
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
                json_mode=True,
            )
        )
        completion_args = CompletionArguments(
            temperature=0.2, max_tokens=2000, response_format="JSON"
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.callback = callback
        self.db = VectorDatabase()
        self.retriever = LectureRetrieval(self.db.client)
        self.suggestion_pipeline = CourseInteractionSuggestionPipeline()

        # Create the pipeline
        self.pipeline = self.llm | StrOutputParser()

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self, dto: CourseChatPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline
            :param dto: The pipeline execution data transfer object
            :param kwargs: The keyword arguments
        """

        # Define tools
        @tool
        def get_exercise_list() -> list[ExerciseWithSubmissionsDTO]:
            """
            Get the list of exercises in the course.
            Use this if the student asks you about an exercise by name, and you don't know the details, such as the ID
            or the schedule. Note: The exercise contains a list of submissions (timestamp and score) of this student so you
            can provide additional context regarding their progress and tendencies over time.
            """
            return dto.course.exercises

        @tool
        def get_course_details() -> dict:
            """
            Get the following course details: course name, course description, programming language, course start date,
            and course end date.
            """
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

        @tool
        def get_student_exercise_metrics(exercise_id: int) -> Union[dict, str]:
            """
            Get the student exercise metrics for the given exercise.
            Important: You have to pass the correct exercise id here. If you don't know it,
            check out the exercise list first and look up the id of the exercise you are interested in.
            UNDER NO CIRCUMSTANCES GUESS THE ID, such as 12345. Always use the correct id.
            The following metrics are returned:
            - global_average_score: The average score of all students in the exercise.
            - score_of_student: The score of the student.
            - global_average_latest_submission: The average relative time of the latest
            submissions of all students in the exercise.
            - latest_submission_of_student: The relative time of the latest submission of the student.
            """
            print(dto.metrics)
            if not dto.metrics or not dto.metrics.exercise_metrics:
                return "No data available!! Do not requery."
            metrics = dto.metrics.exercise_metrics
            if metrics.score and exercise_id in metrics.score:
                return {
                    "global_average_score": metrics.average_score[exercise_id],
                    "score_of_student": metrics.score[exercise_id],
                    "global_average_latest_submission": metrics.average_latest_submission[
                        exercise_id
                    ],
                    "latest_submission_of_student": metrics.latest_submission[
                        exercise_id
                    ],
                }
            else:
                return "No data available! Do not requery."

        @tool
        def get_competency_list() -> list:
            """
            Get the list of competencies in the course.
            Exercises might be associated with competencies. A competency is a skill or knowledge that a student
            should have after completing the course, and instructors may add lectures and exercises to these competencies.
            You can use this if the students asks you about a competency, or if you want to provide additional context
            regarding their progress overall or in a specific area.
            A competency has the following attributes: name, description, taxonomy, soft due date, optional, and mastery threshold.
            The response may include metrics for each competency, such as progress and confidence (0%-100%). These are system-generated.
            The judgment of learning (JOL) values indicate the self-reported confidence by the student (0-5, 5 star). The object
            describing it also indicates the system-computed confidence at the time when the student added their JoL assessment.
            """
            if not dto.metrics or not dto.metrics.competency_metrics:
                return dto.course.competencies
            competency_metrics = dto.metrics.competency_metrics
            weight = 2.0 / 3.0
            return [
                {
                    "info": competency_metrics.competency_information[comp],
                    "exercise_ids": competency_metrics.exercises[comp],
                    "progress": competency_metrics.progress[comp],
                    "confidence": competency_metrics.confidence[comp],
                    "mastery": (
                        (1 - weight) * competency_metrics.progress.get(comp, 0)
                        + weight * competency_metrics.confidence.get(comp, 0)
                    ),
                    "judgment_of_learning": (
                        competency_metrics.jol_values[comp].json()
                        if competency_metrics.jol_values
                        and comp in competency_metrics.jol_values
                        else None
                    ),
                }
                for comp in competency_metrics.competency_information
            ]

        @tool
        def ask_lecture_helper(prompt: str) -> str:
            """
            You have access to the lecture helper. It is an internal tool, just for you, our AI, to help you
            gain knowledge from the course slides. Internally, it will take your prompt, search a vector database (RAG)
            and return the most relevant paragraphs from the interpreted course slides. They will also include references
            aka the slide number and the lecture number so you can tell the student where to find more info.
            The prompt can just be something you want to know, and the lecture helper will try to find the most relevant
            information for you. Ask in natural language.
            Use this tool if you need to look up information in the course slides to answer the message.
            Under no circumstances use this tool twice.
            """
            retrieved_lecture_chunks = self.retriever(
                chat_history=history,
                student_query=prompt,
                result_limit=3,
                course_name=dto.course.name,
            )
            concat_text_content = ""
            for i, chunk in enumerate(retrieved_lecture_chunks):
                text_content_msg = (
                    f" \n Content: {chunk.get(LectureSchema.PAGE_TEXT_CONTENT.value)}\n"
                    f" \n Slide number: {chunk.get(LectureSchema.PAGE_NUMBER.value)}\n"
                    f" \n Lecture name: {chunk.get(LectureSchema.LECTURE_NAME.value)}\n"
                )
                text_content_msg = text_content_msg.replace("{", "{{").replace(
                    "}", "}}"
                )
                concat_text_content += text_content_msg
            return concat_text_content

        if dto.user.id % 3 < 2:
            iris_initial_system_prompt = tell_iris_initial_system_prompt
            begin_agent_prompt = tell_begin_agent_prompt
            chat_history_exists_prompt = tell_chat_history_exists_prompt
            no_chat_history_prompt = tell_no_chat_history_prompt
            format_reminder_prompt = tell_format_reminder_prompt
            begin_agent_jol_prompt = tell_begin_agent_jol_prompt
        else:
            iris_initial_system_prompt = elicit_iris_initial_system_prompt
            begin_agent_prompt = elicit_begin_agent_prompt
            chat_history_exists_prompt = elicit_chat_history_exists_prompt
            no_chat_history_prompt = elicit_no_chat_history_prompt
            format_reminder_prompt = elicit_format_reminder_prompt
            begin_agent_jol_prompt = elicit_begin_agent_jol_prompt

        try:
            logger.info("Running course chat pipeline...")
            history: List[PyrisMessage] = dto.chat_history or []
            query: Optional[PyrisMessage] = (
                dto.chat_history[-1] if dto.chat_history else None
            )

            # Set up the initial prompt
            initial_prompt_with_date = iris_initial_system_prompt.replace(
                "{current_date}",
                datetime.now(tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )

            params = {}
            if self.variant == "jol":
                comp = next(
                    (
                        c
                        for c in dto.course.competencies
                        if c.id == dto.competency_jol.competency_id
                    ),
                    None,
                )
                agent_prompt = begin_agent_jol_prompt
                params = {
                    "jol": json.dumps(
                        {
                            "value": dto.competency_jol.jol_value,
                            "competency_mastery": get_mastery(
                                dto.competency_jol.competency_progress,
                                dto.competency_jol.competency_confidence,
                            ),
                        }
                    ),
                    "competency": comp.json(),
                }
            else:
                agent_prompt = (
                    begin_agent_prompt if query is not None else no_chat_history_prompt
                )

            if query is not None:
                # Add the conversation to the prompt
                chat_history_messages = [
                    convert_iris_message_to_langchain_message(message)
                    for message in history
                ]
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        (
                            "system",
                            initial_prompt_with_date
                            + "\n"
                            + chat_history_exists_prompt,
                        ),
                        *chat_history_messages,
                        ("system", agent_prompt + format_reminder_prompt),
                    ]
                )
            else:
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        (
                            "system",
                            initial_prompt_with_date
                            + "\n"
                            + agent_prompt
                            + "\n"
                            + format_reminder_prompt,
                        ),
                    ]
                )

            tools = [
                get_course_details,
                get_exercise_list,
                get_student_exercise_metrics,
                get_competency_list,
                ask_lecture_helper,
            ]
            agent = create_structured_chat_agent(
                llm=self.llm, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(
                agent=agent, tools=tools, verbose=True, max_iterations=10
            )

            out = None
            self.callback.in_progress()
            for step in agent_executor.iter(params):
                print("STEP:", step)
                if output := step.get("intermediate_step"):
                    action, value = output[0]
                    if action.tool == "get_student_metrics":
                        self.callback.in_progress("Checking your statistics ...")
                    elif action.tool == "get_exercise_list":
                        self.callback.in_progress("Reading exercise list ...")
                    elif action.tool == "get_course_details":
                        self.callback.in_progress("Reading course details ...")
                    elif action.tool == "get_competency_list":
                        self.callback.in_progress("Reading competency list ...")
                    elif action.tool == "ask_lecture_helper":
                        self.callback.in_progress("Searching course slides ...")
                elif step["output"]:
                    out = step["output"]

            print(out)
            suggestions = None
            try:
                if out:
                    suggestion_dto = (
                        CourseChatInteractionSuggestionPipelineExecutionDTO(
                            chat_history=history,
                            last_message=out,
                        )
                    )
                    suggestions = self.suggestion_pipeline(suggestion_dto)
            except Exception as e:
                logger.error(
                    f"An error occurred while running the course chat interaction suggestion pipeline",
                    exc_info=e,
                )
                traceback.print_exc()

            self.callback.done(None, final_result=out, suggestions=suggestions)
        except Exception as e:
            logger.error(
                f"An error occurred while running the course chat pipeline", exc_info=e
            )
            traceback.print_exc()
            self.callback.error(
                "An error occurred while running the course chat pipeline."
            )


def datetime_to_string(dt: Optional[datetime]) -> str:
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
