import logging
import traceback
from datetime import datetime
from typing import List, Optional, Union

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
from ...domain.data.exercise_dto import ExerciseDTO
from ...llm import CapabilityRequestHandler, RequirementList
from ..prompts.iris_course_chat_prompts import (
    iris_initial_system_prompt,
    begin_agent_prompt,
    final_system_prompt,
    guide_system_prompt,
)
from ...domain import CourseChatPipelineExecutionDTO
from ...web.status.status_update import (
    CourseChatStatusCallback,
)
from ...llm import CompletionArguments
from ...llm.langchain import IrisLangchainChatModel

from ..pipeline import Pipeline

logger = logging.getLogger(__name__)


class CourseChatPipeline(Pipeline):
    """Course chat pipeline that answers course related questions from students."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: CourseChatStatusCallback
    prompt: ChatPromptTemplate

    def __init__(self, callback: CourseChatStatusCallback):
        super().__init__(implementation_id="course_chat_pipeline")
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
        def get_exercise_list() -> list[ExerciseDTO]:
            """
            Get the list of exercises in the course.
            Use this if the student asks you about an exercise by name, and you don't know the details, such as the ID
            or the schedule.
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
        def get_student_exercise_metrics(exercise_id: int) -> Union[dict, str]:
            """
            Get the student exercise metrics for the given exercise.
            Important: You have to pass the correct exercise id here. If you don't know it,
            check out the exercise list first and look up the id of the exercise you are interested in.

            UNDER NO CIRCUMSTANCES GUESS THE ID, such as 12345. Always use the correct id.

            The following metrics are returned:
            -
            global_average_score: The average score of all students in the exercise.
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
            The response may include metrics for each competency, such as progress and confidence.
            """
            if not dto.metrics or not dto.metrics.competency_metrics:
                return dto.course.competencies
            competency_metrics = dto.metrics.competency_metrics
            return [{
                "info": competency_metrics.competency_information[comp],
                "exercise_ids": competency_metrics.exercises[comp],
                "progress": competency_metrics.progress[comp],
                "confidence": competency_metrics.confidence[comp]
            } for comp in competency_metrics.competency_information]

        try:
            # Set up the initial prompt
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", iris_initial_system_prompt),
                ]
            )
            logger.info("Running course chat pipeline...")
            history: List[PyrisMessage] = dto.base.chat_history[:-1] or []
            query: PyrisMessage = (
                dto.base.chat_history[-1] if dto.base.chat_history else None
            )

            # Add the conversation to the prompt
            chat_history_messages = [
                convert_iris_message_to_langchain_message(message) for message in history
            ]
            self.prompt += ChatPromptTemplate.from_messages(chat_history_messages)
            self.prompt += ChatPromptTemplate.from_messages(
                [
                    ("system", begin_agent_prompt),
                ]
            )

            tools = [get_course_details, get_exercise_list, get_student_exercise_metrics, get_competency_list]
            agent = create_structured_chat_agent(
                llm=self.llm, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(
                agent=agent, tools=tools, verbose=True, max_iterations=3
            )

            params = {
                "input": (
                    query.contents[0].text_content
                    if query
                    else ""
                )
            }
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
