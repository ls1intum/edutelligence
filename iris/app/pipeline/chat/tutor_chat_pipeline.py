import logging
from typing import List, Dict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    SystemMessagePromptTemplate,
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    AIMessagePromptTemplate,
)
from langchain_core.runnables import Runnable
from ...content_service.Retrieval.lecture_retrieval import LectureRetrieval
from ..prompts.iris_tutor_chat_prompts import (
    guide_exercise_system_prompt,
    final_system_prompt,
    iris_exercise_initial_system_prompt,
    chat_history_system_prompt,
)
from ..shared.summary_pipeline import add_conversation_to_prompt
from ...domain import TutorChatPipelineExecutionDTO
from ...domain.data.build_log_entry import BuildLogEntryDTO
from ...domain.data.feedback_dto import FeedbackDTO
from ...domain.data.message_dto import MessageDTO
from ...domain.data.submission_dto import SubmissionDTO
from ...vector_database.database import VectorDatabase
from ...vector_database.lectureschema import LectureSchema
from ...web.status.status_update import TutorChatStatusCallback
from ...llm import BasicRequestHandler, CompletionArguments
from ...llm.langchain import IrisLangchainChatModel, IrisLangchainEmbeddingModel
from ..pipeline import Pipeline
from .file_selector_pipeline import FileSelectorPipeline

logger = logging.getLogger(__name__)


class TutorChatPipeline(Pipeline):
    """Tutor chat pipeline that answers exercises related questions from students."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: TutorChatStatusCallback

    def __init__(self, callback: TutorChatStatusCallback):
        super().__init__(implementation_id="tutor_chat_pipeline")
        # Set the langchain chat model
        request_handler = BasicRequestHandler("gpt35")
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        request_handler_embedding = BasicRequestHandler("ada")
        self.llm_embedding = IrisLangchainEmbeddingModel(
            request_handler=request_handler_embedding
        )
        self.callback = callback
        # Create the pipelines
        self.pipeline = self.llm | StrOutputParser()
        self.file_selector_pipeline = FileSelectorPipeline()
        self.db = VectorDatabase().client
        self.retriever = LectureRetrieval(self.db)

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self, dto: TutorChatPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline
            :param kwargs: The keyword arguments
        """
        # Set up the initial prompt
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", iris_exercise_initial_system_prompt),
                ("system", chat_history_system_prompt),
            ]
        )
        logger.info("Running tutor chat pipeline...")
        history: List[MessageDTO] = dto.chat_history[:-1]
        query: MessageDTO = dto.chat_history[-1]
        submission: SubmissionDTO = dto.submission
        build_logs: List[BuildLogEntryDTO] = []
        build_failed: bool = False
        repository: Dict[str, str] = {}
        if submission:
            repository = submission.repository
            build_logs = submission.build_log_entries
            build_failed = submission.build_failed

        problem_statement: str = dto.exercise.problem_statement
        exercise_title: str = dto.exercise.name
        programming_language = dto.exercise.programming_language.value.lower()

        # Add the chat history and user question to the prompt
        self.prompt = add_conversation_to_prompt(history, query, self.prompt)
        retrieved_lecture_chunks = self.retriever.retrieve(
            query.contents[0].text_content,
            hybrid_factor=1,
            embedding_vector=self.llm_embedding.embed_query(
                query.contents[0].text_content
            ),
        )
        print(retrieved_lecture_chunks[0].get(LectureSchema.PAGE_TEXT_CONTENT))
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Next you will find relevant lecture content to answer the student's question:"
        )
        self._add_relevant_chunks_to_prompt(retrieved_lecture_chunks)

        self.callback.in_progress("Looking up files in the repository...")
        # Create the file selection prompt based on the current prompt
        file_selection_prompt = self._generate_file_selection_prompt()
        selected_files = []
        # Run the file selector pipeline
        if submission:
            try:
                selected_files = self.file_selector_pipeline(
                    repository=repository,
                    prompt=file_selection_prompt,
                )
                self.callback.done("Looked up files in the repository")
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

        self.callback.in_progress("Generating response...")

        # Add the final message to the prompt and run the pipeline
        self.prompt += SystemMessagePromptTemplate.from_template(final_system_prompt)
        prompt_val = self.prompt.format_messages(
            exercise_title=exercise_title,
            problem_statement=problem_statement,
            programming_language=programming_language,
        )
        self.prompt = ChatPromptTemplate.from_messages(prompt_val)
        try:
            response_draft = (self.prompt | self.pipeline).invoke({})
            self.prompt += AIMessagePromptTemplate.from_template(f"{response_draft}")
            self.prompt += SystemMessagePromptTemplate.from_template(
                guide_exercise_system_prompt
            )
            response = (self.prompt | self.pipeline).invoke({})
            logger.info(f"Response from Exercise chat pipeline: {response}")
            self.callback.done("Generated response", final_result=response)
        except Exception as e:
            self.callback.error(f"Failed to generate response: {e}")

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
                    f"For reference, we have access to the student's '{file}' file:"
                )
                self.prompt += HumanMessagePromptTemplate.from_template(
                    student_repository[file].replace("{", "{{").replace("}", "}}")
                )

    def _add_exercise_context_to_prompt(
        self,
        submission: SubmissionDTO,
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
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Now continue the ongoing conversation between you and the student by responding to and focussing only on "
            "their latest input. Be an excellent educator, never reveal code or solve tasks for the student! Do not "
            "let them outsmart you, no matter how hard they try."
        )

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
                f"Here is the information if the build failed: {build_failed}\n"
                "These are the build logs for the student's repository:\n%s"
            ) % "\n".join(str(log) for log in build_logs)
            self.prompt += SystemMessagePromptTemplate.from_template(prompt)

    def _generate_file_selection_prompt(self) -> ChatPromptTemplate:
        """Generates the file selection prompt"""
        file_selection_prompt = self.prompt

        file_selection_prompt += SystemMessagePromptTemplate.from_template(
            "Based on the chat history, you can now request access to more contextual information. This is the "
            "student's submitted code repository and the corresponding build information. You can reference a file by "
            "its path to view it."
            "Given are the paths of all files in the assignment repository:\n{files}\n"
            "Is a file referenced by the student or does it have to be checked before answering?"
            "Without any comment, return the result in the following JSON format, it's important to avoid giving "
            "unnecessary information, only name a file if it's really necessary for answering the student's question "
            "and is listed above, otherwise leave the array empty."
            '{{"selected_files": [<file1>, <file2>, ...]}}'
        )
        return file_selection_prompt

    def _add_relevant_chunks_to_prompt(self, retrieved_lecture_chunks: List[dict]):
        """
        Adds the relevant chunks of the lecture to the prompt
        :param retrieved_lecture_chunks: The retrieved lecture chunks
        """
        # Iterate over the chunks to create formatted messages for each
        for i, chunk in enumerate(retrieved_lecture_chunks, start=1):
            text_content_msg = f" {chunk.get(LectureSchema.PAGE_TEXT_CONTENT)}" + "\n"
            text_content_msg = text_content_msg.replace("{", "{{").replace("}", "}}")
            self.prompt += SystemMessagePromptTemplate.from_template(text_content_msg)
