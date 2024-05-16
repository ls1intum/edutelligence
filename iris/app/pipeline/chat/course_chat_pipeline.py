import logging
from datetime import datetime
from typing import List, Optional, Union

from langchain.agents import create_structured_chat_agent, AgentExecutor
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    AIMessagePromptTemplate, MessagesPlaceholder,
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
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000, response_format="JSON")
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
                "course_name": dto.course.name,
                "course_description": dto.course.description,
                "programming_language": dto.course.default_programming_language,
                "course_start_date": datetime_to_string(dto.course.start_time),
                "course_end_date": datetime_to_string(dto.course.end_time),
            }

        @tool
        def get_student_metrics(exercise_id: int) -> Union[dict, str]:
            """
            Get the student metrics for the given exercise.
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
            metrics = dto.metrics.exercise_metrics
            if metrics and exercise_id in metrics.score:
                return {
                    "global_average_score": metrics.average_score[exercise_id],
                    "score_of_student": metrics.score[exercise_id],
                    "global_average_latest_submission": metrics.average_latest_submission[exercise_id],
                    "latest_submission_of_student": metrics.latest_submission[exercise_id],
                }
            else:
                return "No data available! Do not requery."

        self.callback.in_progress()

        # Set up the initial prompt
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", iris_initial_system_prompt),
            ]
        )
        logger.info("Running course chat pipeline...")
        history: List[PyrisMessage] = dto.base.chat_history[:-1] or []
        query: PyrisMessage = dto.base.chat_history[-1] if dto.base.chat_history else None
        name: str = dto.course.name or "No name provided"
        description: str = dto.course.description or "No description provided"
        programming_language: str = dto.course.default_programming_language or "No programming language provided"
        start_date: str = datetime_to_string(dto.course.start_time) if dto.course.start_time else "No start date provided"
        end_date: str = datetime_to_string(dto.course.end_time) if dto.course.end_time else "No end date provided"

        print(dto.metrics)


        # Add the conversation to the prompt
        chat_history_messages = [
            convert_iris_message_to_langchain_message(message)
            for message in history
        ]
        self.prompt += ChatPromptTemplate.from_messages(chat_history_messages)
        self.prompt += ChatPromptTemplate.from_messages([
            ("system", begin_agent_prompt),
        ])

        tools = [get_course_details, get_exercise_list, get_student_metrics]
        agent = create_structured_chat_agent(llm=self.llm, tools=tools, prompt=self.prompt)
        agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=3)

        out = agent_executor.invoke({"input": "Latest student message: " + query.contents[0].text_content})
        print(out)

        self.callback.done(None, final_result=out['output'])
        return

        # Add the final message to the prompt and run the pipeline
        prompt_val = self.prompt.format_messages()
        self.prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response_draft = (self.prompt | self.pipeline).invoke({})
            print("THE RESPONSE DRAFT IS: ", response_draft)
            self.prompt += AIMessagePromptTemplate.from_template(f"{response_draft}")
            self.prompt += SystemMessagePromptTemplate.from_template(
                guide_system_prompt
            )
            response = (self.prompt | self.pipeline).invoke({})
            logger.info(f"Response from tutor chat pipeline: {response}")
            self.callback.done(None, final_result=response)
        except Exception as e:
            self.callback.error(f"Failed to generate response: {e}")


    def _add_conversation_to_prompt(
        self,
        chat_history: List[PyrisMessage],
        user_question: PyrisMessage,
    ):
        """
        Adds the chat history and user question to the prompt
            :param chat_history: The chat history
            :param user_question: The user question
            :return: The prompt with the chat history
        """
        if chat_history is not None and len(chat_history) > 0:

 #           self.prompt += chat_history_messages
            self.prompt += SystemMessagePromptTemplate.from_template(
                "Now, consider the student's newest and latest input:"
            )
        self.prompt += convert_iris_message_to_langchain_message(user_question)


def datetime_to_string(dt: Optional[datetime]) -> str:
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")