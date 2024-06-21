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
    PromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable
from weaviate.collections.classes.filters import Filter

from .file_selector_pipeline import FileSelectorPipeline
from .lecture_chat_pipeline import LectureChatPipeline
from .output_models.output_models.selected_paragraphs import SelectedParagraphs
from ..pipeline import Pipeline
from ..prompts.iris_exercise_chat_prompts import (
    iris_initial_system_prompt,
    chat_history_system_prompt,
    final_system_prompt,
    guide_system_prompt,
)
from ..shared.reranker_pipeline import RerankerPipeline
from ...common import convert_iris_message_to_langchain_message
from ...domain import ExerciseChatPipelineExecutionDTO
from ...domain import PyrisMessage
from ...domain.chat.lecture_chat.lecture_chat_pipeline_execution_dto import (
    LectureChatPipelineExecutionDTO,
)
from ...domain.data.build_log_entry import BuildLogEntryDTO
from ...domain.data.feedback_dto import FeedbackDTO
from ...domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ...llm import CapabilityRequestHandler, RequirementList
from ...llm import CompletionArguments
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.lecture_retrieval import LectureRetrieval
from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_schema import LectureSchema
from ...web.status.status_update import ExerciseChatStatusCallback

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ExerciseChatPipeline(Pipeline):
    """Exercise chat pipeline that answers exercises related questions from students."""

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
        self.db = VectorDatabase()
        self.retriever = LectureRetrieval(self.db.client)
        self.reranker_pipeline = RerankerPipeline()
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
            should_execute_lecture_pipeline = self.should_execute_lecture_pipeline(
                dto.course.id
            )
            self.lecture_chat_response = ""
            if should_execute_lecture_pipeline:
                execution_dto = LectureChatPipelineExecutionDTO(
                    settings=dto.settings,
                    course=dto.course,
                    chatHistory=dto.chat_history,
                    user=dto.user,
                )
                lecture_chat_thread = threading.Thread(
                    target=self._run_lecture_chat_pipeline(execution_dto), args=(dto,)
                )
                lecture_chat_thread.start()

            tutor_chat_thread = threading.Thread(
                target=self._run_exercise_chat_pipeline(dto),
                args=(dto, should_execute_lecture_pipeline),
            )
            tutor_chat_thread.start()
            response = self.choose_best_response(
                [self.exercise_chat_response, self.lecture_chat_response],
                dto.chat_history[-1].contents[0].text_content,
                dto.chat_history,
            )
            self.callback.done("Generated response", final_result=response)
        except Exception as e:
            traceback.print_exc()
            self.callback.error(f"Failed to generate response: {e}")

    def choose_best_response(
        self, paragraphs: list[str], query: str, chat_history: List[PyrisMessage]
    ):
        """
        Chooses the best response from the reranker pipeline
        :param paragraphs: The paragraphs
        :param query: The query
        :return: The best response
        """
        dirname = os.path.dirname(__file__)
        prompt_file_path = os.path.join(
            dirname, "..", "prompts", "choose_response_prompt.txt"
        )
        with open(prompt_file_path, "r") as file:
            logger.info("Loading reranker prompt...")
            prompt_str = file.read()

        output_parser = PydanticOutputParser(pydantic_object=SelectedParagraphs)
        choose_response_prompt = PromptTemplate(
            template=prompt_str,
            input_variables=["question", "paragraph_0", "paragraph_1", "chat_history"],
            partial_variables={
                "format_instructions": output_parser.get_format_instructions()
            },
        )
        paragraph_index = self.reranker_pipeline(
            paragraphs=paragraphs,
            query=query,
            prompt=choose_response_prompt,
            chat_history=chat_history,
        )[0]
        try:
            chosen_paragraph = paragraphs[int(paragraph_index)]
        except Exception as e:
            chosen_paragraph = paragraphs[0]
            logger.error(f"Failed to choose best response: {e}")
        return chosen_paragraph

    def _run_lecture_chat_pipeline(self, dto: LectureChatPipelineExecutionDTO):
        pipeline = LectureChatPipeline()
        self.lecture_chat_response = pipeline(dto=dto)

    def _run_exercise_chat_pipeline(
        self,
        dto: ExerciseChatPipelineExecutionDTO,
        should_execute_lecture_pipeline: bool = False,
    ):
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
                    feedbacks=(
                        submission.latest_result.feedbacks
                        if submission and submission.latest_result
                        else []
                    ),
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

        if should_execute_lecture_pipeline:
            retrieved_lecture_chunks = self.retriever(
                chat_history=history,
                student_query=query.contents[0].text_content,
                result_limit=5,
                course_name=dto.course.name,
                problem_statement=problem_statement,
                exercise_title=exercise_title,
                course_id=dto.course.id,
                base_url=dto.settings.artemis_base_url,
            )
            self._add_relevant_chunks_to_prompt(retrieved_lecture_chunks)

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
            response_draft = (
                (self.prompt | self.pipeline)
                .with_config({"run_name": "Response Drafting"})
                .invoke({})
            )
            self.prompt = ChatPromptTemplate.from_messages(
                [
                    SystemMessagePromptTemplate.from_template(guide_system_prompt),
                ]
            )
            prompt_val = self.prompt.format_messages(response=response_draft)
            self.prompt = ChatPromptTemplate.from_messages(prompt_val)

            guide_response = (
                (self.prompt | self.pipeline)
                .with_config({"run_name": "Response Refining"})
                .invoke({})
            )

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

    def _add_relevant_chunks_to_prompt(self, retrieved_lecture_chunks: List[dict]):
        """
        Adds the relevant chunks of the lecture to the prompt
        :param retrieved_lecture_chunks: The retrieved lecture chunks
        """
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Next you will find the potentially relevant lecture content to answer the student message:\n"
        )
        for i, chunk in enumerate(retrieved_lecture_chunks):
            text_content_msg = (
                f" \n {chunk.get(LectureSchema.PAGE_TEXT_CONTENT.value)} \n"
            )
            text_content_msg = text_content_msg.replace("{", "{{").replace("}", "}}")
            self.prompt += SystemMessagePromptTemplate.from_template(text_content_msg)
        self.prompt += SystemMessagePromptTemplate.from_template(
            "USE ONLY THE CONTENT YOU NEED TO ANSWER THE QUESTION:\n"
        )

    def should_execute_lecture_pipeline(self, course_id: int) -> bool:
        """
        Checks if the lecture pipeline should be executed
        :param course_id: The course ID
        :return: True if the lecture pipeline should be executed
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
