import json
import logging
import traceback
import typing
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

from ...common import convert_iris_message_to_langchain_message
from ...domain import PyrisMessage
from ...domain.data.exercise_with_submissions_dto import ExerciseWithSubmissionsDTO
from ...llm import CapabilityRequestHandler, RequirementList
from ..prompts.iris_course_chat_prompts import (
    tell_iris_initial_system_prompt,
    tell_begin_agent_prompt, tell_chat_history_exists_prompt, tell_no_chat_history_prompt, tell_format_reminder_prompt,
    tell_begin_agent_jol_prompt
)
from ..prompts.iris_course_chat_prompts_elicit import (
    elicit_iris_initial_system_prompt,
    elicit_begin_agent_prompt, elicit_chat_history_exists_prompt, elicit_no_chat_history_prompt, elicit_format_reminder_prompt,
    elicit_begin_agent_jol_prompt
)
from ...domain import CourseChatPipelineExecutionDTO
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
            temperature=0, max_tokens=2000, response_format="JSON"
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.callback = callback

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

        used_tools = []
        # Define tools
        @tool
        def get_exercise_list() -> list[dict]:
            """
            Get the list of exercises in the course.
            Use this if the student asks you about an exercise. Note: The exercise contains a list of submissions (timestamp and score) of this student so you
            can provide additional context regarding their progress and tendencies over time.
            Also, ensure to use the provided current date and time and compare it to the start date and due date etc.
            Do not recommend that the student should work on exercises with a past due date.
            The submissions array tells you about the status of the student in this exercise: You see when the student submitted the exercise and what score they got.
            A 100% score means the student solved the exercise correctly and completed it.
            """
            used_tools.append("get_exercise_list")
            current_time = datetime.now(tz=pytz.UTC)
            exercises = []
            for exercise in dto.course.exercises:
                exercise_dict = exercise.dict()
                exercise_dict["due_date_over"] = exercise.due_date < current_time if exercise.due_date else None
                exercises.append(exercise_dict)
            return exercises


        @tool
        def get_course_details() -> dict:
            """
            Get the following course details: course name, course description, programming language, course start date,
            and course end date.
            """
            used_tools.append("get_course_details")
            return {
                "course_name": (
                    dto.course.name if dto.course else "No course provided"
                ),
                "course_description": (
                    dto.course.description if dto.course and dto.course.description
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
        def get_student_exercise_metrics(exercise_ids: typing.List[int]) -> Union[dict[int, dict], str]:
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
            print(dto.metrics)
            if not dto.metrics or not dto.metrics.exercise_metrics:
                return "No data available!! Do not requery."
            metrics = dto.metrics.exercise_metrics
            if metrics.score and any(exercise_id in metrics.score for exercise_id in exercise_ids):
                return {
                    exercise_id: {
                        "global_average_score": metrics.average_score[exercise_id],
                        "score_of_student": metrics.score.get(exercise_id, None),
                        "global_average_latest_submission": metrics.average_latest_submission.get(exercise_id, None),
                        "latest_submission_of_student": metrics.latest_submission.get(exercise_id, None),
                    }
                    for exercise_id in exercise_ids if exercise_id in metrics.average_score
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
            used_tools.append("get_competency_list")
            if not dto.metrics or not dto.metrics.competency_metrics:
                return dto.course.competencies
            competency_metrics = dto.metrics.competency_metrics
            weight = 2.0 / 3.0
            return [{
                "info": competency_metrics.competency_information.get(comp, None),
                "exercise_ids": competency_metrics.exercises.get(comp, []),
                "progress": competency_metrics.progress.get(comp, 0),
                "confidence": competency_metrics.confidence.get(comp, 0),
                "mastery": ((1 - weight) * competency_metrics.progress.get(comp, 0)
                            + weight * competency_metrics.confidence.get(comp, 0)),
                "judgment_of_learning":  competency_metrics.jol_values.get[comp].json() if competency_metrics.jol_values and comp in competency_metrics.jol_values else None,
            } for comp in competency_metrics.competency_information]

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
            history: List[PyrisMessage] = dto.chat_history[-5:] or []
            query: Optional[PyrisMessage] = (dto.chat_history[-1] if dto.chat_history else None)

            # Set up the initial prompt
            initial_prompt_with_date = iris_initial_system_prompt.replace("{current_date}",
                                                                          datetime.now(tz=pytz.UTC).strftime(
                                                                              "%Y-%m-%d %H:%M:%S"))

            params = {}
            if self.variant == "jol":
                comp = next((c for c in dto.course.competencies if c.id == dto.competency_jol.competency_id), None)
                agent_prompt = begin_agent_jol_prompt
                params = {
                    "jol": json.dumps({
                        "value": dto.competency_jol.jol_value,
                        "competency_mastery": get_mastery(dto.competency_jol.competency_progress, dto.competency_jol.competency_confidence),
                    }),
                    "competency": comp.json(),
                }
            else:
                agent_prompt = begin_agent_prompt if query is not None else no_chat_history_prompt
                params = {
                    "course_name": dto.course.name if dto.course else "<Unknown course name>",
                }

            if query is not None:
                # Add the conversation to the prompt
                chat_history_messages = [convert_iris_message_to_langchain_message(message) for message in history]
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        ("system", initial_prompt_with_date + "\n" + chat_history_exists_prompt + "\n" + agent_prompt),
                        *chat_history_messages,
                        ("system", format_reminder_prompt)
                    ]
                )
            else:
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        ("system", initial_prompt_with_date + "\n" +
                         agent_prompt + "\n" + format_reminder_prompt),
                    ]
                )

            tools = [get_course_details, get_exercise_list, get_student_exercise_metrics, get_competency_list]
            agent = create_structured_chat_agent(
                llm=self.llm, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(
                agent=agent, tools=tools, verbose=True, max_iterations=5
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
                elif step['output']:
                    out = step['output']

            print(out)
            self.callback.done(None, final_result=out)
        except Exception as e:
            logger.error(f"An error occurred while running the course chat pipeline", exc_info=e)
            traceback.print_exc()
            self.callback.error("An error occurred while running the course chat pipeline.")


def datetime_to_string(dt: Optional[datetime]) -> str:
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
