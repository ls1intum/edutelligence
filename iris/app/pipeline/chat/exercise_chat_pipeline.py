import logging
import os
import threading
import traceback
from typing import List, Dict

from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
    AIMessagePromptTemplate,
    PromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable

from ...common import convert_iris_message_to_langchain_message
from ...domain import PyrisMessage
from ...llm import CapabilityRequestHandler, RequirementList
from ...domain.data.build_log_entry import BuildLogEntryDTO
from ...domain.data.feedback_dto import FeedbackDTO
from ..prompts.iris_exercise_chat_prompts import (
    iris_initial_system_prompt,
    chat_history_system_prompt,
    final_system_prompt,
    guide_system_prompt,
)
from ...domain import ExerciseChatPipelineExecutionDTO
from ...domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ...web.status.status_update import ExerciseChatStatusCallback
from .file_selector_pipeline import FileSelectorPipeline
from ...llm import CompletionArguments
from ...llm.langchain import IrisLangchainChatModel

from ..pipeline import Pipeline

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ExerciseChatPipeline(Pipeline):
    """Exercise chat pipeline that answers exercises related questions from students. """

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: ExerciseChatStatusCallback
    file_selector_pipeline: FileSelectorPipeline
    prompt: ChatPromptTemplate

    def __init__(self, callback: ExerciseChatStatusCallback):
        super().__init__(implementation_id="exercise_chat_pipeline")
        # Set the langchain chat model
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=3.5,
                context_length=16385,
            )
        )
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.callback = callback

        # Create the pipelines
        self.file_selector_pipeline = FileSelectorPipeline()
        self.pipeline = self.llm | StrOutputParser()

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Exercise + Lecture Chat Combined Pipeline")
    def __call__(self, dto: ExerciseChatPipelineExecutionDTO):
        """
        Runs the pipeline
        :param dto:  execution data transfer object
        :param kwargs: The keyword arguments
        """
        try:
            self._run_exercise_chat_pipeline(dto)
            logger.info(f"Response from exercise chat pipeline: {self.exercise_chat_response}")
            self.callback.done("Generated response", final_result=self.exercise_chat_response)
        except Exception as e:
            self.callback.error(f"Failed to generate response: {e}")

    def _run_exercise_chat_pipeline(self, dto: ExerciseChatPipelineExecutionDTO):
        """
        Runs the pipeline
        :param dto:  execution data transfer object
        :param kwargs: The keyword arguments
        """
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", iris_initial_system_prompt),
                ("system", chat_history_system_prompt),
            ]
        )
        logger.info("Running exercise chat pipeline...")
        history: List[PyrisMessage] = dto.chat_history[:-1]
        query: PyrisMessage = dto.chat_history[-1]

        submission: ProgrammingSubmissionDTO = dto.submission
        build_logs: List[BuildLogEntryDTO] = []
        build_failed: bool = False
        repository: Dict[str, str] = {}
        if submission:
            repository = submission.repository
            build_logs = submission.build_log_entries
            build_failed = submission.build_failed

        problem_statement: str = dto.exercise.problem_statement
        exercise_title: str = dto.exercise.name
        programming_language = dto.exercise.programming_language.lower()

        # Add the chat history and user question to the prompt
        self._add_conversation_to_prompt(history, query)

        self.callback.in_progress()
        selected_files = []
        # Run the file selector pipeline
        if submission:
            try:
                selected_files = self.file_selector_pipeline(
                    chat_history=history,
                    question=query,
                    repository=repository,
                    feedbacks=(submission.latest_result.feedbacks if submission and submission.latest_result else [])
                )
                self.callback.done()
            except Exception as e:
                self.callback.error(f"Failed to look up files in the repository: {e}")
                return

            self._add_build_logs_to_prompt(build_logs, build_failed)
        else:
            self.callback.skip("No submission found")
        # Add the exercise context to the prompt
        self._add_exercise_context_to_prompt(
            submission,
            selected_files,
        )

        self.callback.in_progress()

        # Add the final message to the prompt and run the pipeline
        self.prompt += SystemMessagePromptTemplate.from_template(final_system_prompt)
        prompt_val = self.prompt.format_messages(
            exercise_title=exercise_title,
            problem_statement=problem_statement,
            programming_language=programming_language,
        )
        self.prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response_draft = (self.prompt | self.pipeline).with_config({"run_name": "Response Drafting"}).invoke({})
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    SystemMessagePromptTemplate.from_template(guide_system_prompt),
                ]
            )
            prompt_val = self.prompt.format_messages(response=response_draft)
            self.prompt = ChatPromptTemplate.from_messages(prompt_val)

            guide_response = (self.prompt | self.pipeline).with_config({"run_name": "Response Refining"}).invoke({})

            if "!ok!" in guide_response:
                print("Response is ok and not rewritten!!!")
                self.exercise_chat_response = response_draft
            else:
                print("Response is rewritten.")
                self.exercise_chat_response = guide_response
        except Exception as e:
            self.callback.error(f"Failed to create response: {e}")
            # print stack trace
            traceback.print_exc()
            return "Failed to generate response"

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
            chat_history_messages = [
                convert_iris_message_to_langchain_message(message)
                for message in chat_history
            ]
            self.prompt += chat_history_messages
            self.prompt += SystemMessagePromptTemplate.from_template(
                "Now, consider the student's newest and latest input:"
            )
        self.prompt += convert_iris_message_to_langchain_message(user_question)

    def _add_student_repository_to_prompt(
        self, student_repository: Dict[str, str], selected_files: List[str]
    ):
        """Adds the student repository to the prompt
        :param student_repository: The student repository
        :param selected_files: The selected files
        """
        for file in selected_files:
            if file in student_repository:
                self.prompt += SystemMessagePromptTemplate.from_template(
                    f"For reference, we have access to the student's '{file}' file: "
                )
                self.prompt += HumanMessagePromptTemplate.from_template(
                    student_repository[file].replace("{", "{{").replace("}", "}}")
                )

    def _add_exercise_context_to_prompt(
        self,
        submission: ProgrammingSubmissionDTO,
        selected_files: List[str],
    ):
        """Adds the exercise context to the prompt
        :param submission: The submission
        :param selected_files: The selected files
        """
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Consider the following exercise context:\n"
            "- Title: {exercise_title}\n"
            "- Problem Statement: {problem_statement}\n"
            "- Exercise programming language: {programming_language}"
        )
        if submission:
            student_repository = submission.repository
            self._add_student_repository_to_prompt(student_repository, selected_files)

    def _add_feedbacks_to_prompt(self, feedbacks: List[FeedbackDTO]):
        """Adds the feedbacks to the prompt
        :param feedbacks: The feedbacks
        """
        if feedbacks is not None and len(feedbacks) > 0:
            prompt = (
                "These are the feedbacks for the student's repository:\n%s"
            ) % "\n---------\n".join(str(log) for log in feedbacks)
            self.prompt += SystemMessagePromptTemplate.from_template(prompt)

    def _add_build_logs_to_prompt(
        self, build_logs: List[BuildLogEntryDTO], build_failed: bool
    ):
        """Adds the build logs to the prompt
        :param build_logs: The build logs
        :param build_failed: Whether the build failed
        """
        if build_logs is not None and len(build_logs) > 0:
            prompt = (
                f"Last build failed: {build_failed}\n"
                "These are the build logs for the student's repository:\n%s"
            ) % "\n".join(str(log) for log in build_logs)
            self.prompt += SystemMessagePromptTemplate.from_template(prompt)
