import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable, get_current_run_tree
from weaviate.collections.classes.filters import Filter

from .code_feedback_pipeline import CodeFeedbackPipeline
from .interaction_suggestion_pipeline import InteractionSuggestionPipeline
from ..pipeline import Pipeline
from ..prompts.iris_exercise_chat_prompts import (
    iris_initial_system_prompt,
    chat_history_system_prompt,
    final_system_prompt,
    guide_system_prompt,
)
from ..shared.citation_pipeline import CitationPipeline
from ..shared.reranker_pipeline import RerankerPipeline
from ...common import convert_iris_message_to_langchain_message
from ...domain import ExerciseChatPipelineExecutionDTO
from ...domain import PyrisMessage
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
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
    suggestion_pipeline: InteractionSuggestionPipeline
    code_feedback_pipeline: CodeFeedbackPipeline
    prompt: ChatPromptTemplate

    def __init__(self, callback: ExerciseChatStatusCallback):
        super().__init__(implementation_id="exercise_chat_pipeline")
        # Set the langchain chat model
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(
                    gpt_version_equivalent=4.5,
                    context_length=16385,
                )
            ),
            completion_args=completion_args,
        )

        self.callback = callback

        # Create the pipelines
        self.db = VectorDatabase()
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant="exercise")
        self.retriever = LectureRetrieval(self.db.client)
        self.reranker_pipeline = RerankerPipeline()
        self.code_feedback_pipeline = CodeFeedbackPipeline()
        self.pipeline = self.llm | StrOutputParser()
        self.citation_pipeline = CitationPipeline()

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    @traceable(name="Exercise Chat Pipeline")
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
            self._run_exercise_chat_pipeline(dto, should_execute_lecture_pipeline),
            self.callback.done(
                "Generated response", final_result=self.exercise_chat_response
            )

            try:
                if self.exercise_chat_response:
                    suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                    suggestion_dto.chat_history = dto.chat_history
                    suggestion_dto.last_message = self.exercise_chat_response
                    suggestion_dto.problem_statement = dto.exercise.problem_statement
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
            traceback.print_exc()
            self.callback.error(f"Failed to generate response: {e}")

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

        self.callback.in_progress()

        rt = get_current_run_tree()
        with ThreadPoolExecutor() as executor:
            # Run the file selector pipeline
            if submission:
                future_feedback = executor.submit(
                    self.code_feedback_pipeline,
                    chat_history=history,
                    question=query,
                    repository=repository,
                    problem_statement=problem_statement,
                    build_failed=build_failed,
                    build_logs=build_logs,
                    feedbacks=(
                        submission.latest_result.feedbacks
                        if submission and submission.latest_result
                        else []
                    ),
                    langsmith_extra={"parent": rt},
                )

            if should_execute_lecture_pipeline:
                future_lecture = executor.submit(
                    self.retriever.basic_lecture_retrieval,
                    chat_history=history,
                    student_query=query.contents[0].text_content,
                    result_limit=3,
                    course_name=dto.course.name,
                    course_id=dto.course.id,
                    base_url=dto.settings.artemis_base_url,
                    langsmith_extra={"parent": rt},
                )

            if submission:
                try:
                    feedback = future_feedback.result()
                    self.prompt += SystemMessagePromptTemplate.from_template(
                        "Another AI has checked the code of the student and has found the following issues. "
                        "Use this information to help the student. "
                        "Do not leak that it is coming from a different AI "
                        "(the student should think it's your own idea)! "
                        "\n" + feedback + "\n"
                        "Remember: This is not coming from the student. This is not a message from the student. "
                        "Is is an automated analysis of the student's code. "
                        "NEVER claim that the student said this, e.g with 'You mentioned...'"
                    )
                except Exception as e:
                    self.callback.error(
                        f"Failed to look up files in the repository: {e}"
                    )
                    return

            # Add the feedbacks to the prompt
            if should_execute_lecture_pipeline:
                try:
                    self.retrieved_lecture_chunks = future_lecture.result()
                    if len(self.retrieved_lecture_chunks) > 0:
                        self._add_relevant_chunks_to_prompt(
                            self.retrieved_lecture_chunks
                        )
                except Exception as e:
                    self.callback.error(f"Failed to retrieve lecture chunks: {e}")
                    return

        self.callback.done()

        self._add_exercise_context_to_prompt(
            submission,
        )
        # Add the chat history and user question to the prompt
        self._add_conversation_to_prompt(history, query)

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
            self.callback.done()
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
                for message in chat_history[-4:]
            ]
            self.prompt += SystemMessagePromptTemplate.from_template(
                chat_history_system_prompt
            )
            self.prompt += chat_history_messages
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Consider the student's newest and latest input:"
        )
        self.prompt += convert_iris_message_to_langchain_message(user_question)

    def _add_exercise_context_to_prompt(
        self,
        submission: ProgrammingSubmissionDTO,
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

    def _add_feedbacks_to_prompt(self, feedbacks: List[FeedbackDTO]):
        """Adds the feedbacks to the prompt
        :param feedbacks: The feedbacks
        """
        if feedbacks is not None and len(feedbacks) > 0:
            prompt = (
                "These are the feedbacks for the student's repository:\n%s"
            ) % "\n---------\n".join(str(log) for log in feedbacks)
            self.prompt += SystemMessagePromptTemplate.from_template(prompt)

    def _add_relevant_chunks_to_prompt(self, retrieved_lecture_chunks: List[dict]):
        """
        Adds the relevant chunks of the lecture to the prompt
        :param retrieved_lecture_chunks: The retrieved lecture chunks
        """
        txt = "Next you will find the potentially relevant lecture content to answer the student message."
        "Use this context to enrich your response.\n"

        for chunk in retrieved_lecture_chunks:
            props = chunk.get("properties", {})
            lct = "Lecture: {}, Page: {}\nContent:\n---{}---\n\n".format(
                props.get(LectureSchema.LECTURE_NAME.value),
                props.get(LectureSchema.PAGE_NUMBER.value),
                props.get(LectureSchema.PAGE_TEXT_CONTENT.value),
            )
            txt += lct

        self.prompt += SystemMessagePromptTemplate.from_template(txt)

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
