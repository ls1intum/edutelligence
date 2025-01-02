import logging
import traceback
from datetime import datetime
from operator import attrgetter
from typing import List

import pytz
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from .code_feedback_pipeline import CodeFeedbackPipeline
from .interaction_suggestion_pipeline import InteractionSuggestionPipeline
from ..pipeline import Pipeline
from ..prompts.iris_exercise_chat_agent_prompts import (
    tell_iris_initial_system_prompt,
    tell_begin_agent_prompt,
    tell_chat_history_exists_prompt,
    tell_no_chat_history_prompt,
    tell_format_reminder_prompt,
    guide_system_prompt,
    tell_build_failed_system_prompt,
    tell_progress_stalled_system_prompt,
)

from ..shared.citation_pipeline import CitationPipeline
from ..shared.reranker_pipeline import RerankerPipeline
from ..shared.utils import generate_structured_tools_from_functions
from ...common.PipelineEnum import PipelineEnum
from ...common.message_converters import convert_iris_message_to_langchain_human_message
from ...common.pyris_message import PyrisMessage, IrisMessageRole
from ...domain import ExerciseChatPipelineExecutionDTO
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...llm import CapabilityRequestHandler, RequirementList
from ...llm import CompletionArguments
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.lecture_retrieval import LectureRetrieval
from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_schema import LectureSchema
from weaviate.collections.classes.filters import Filter
from ...web.status.status_update import ExerciseChatStatusCallback

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def add_exercise_context_to_prompt(
    exercise_title, problem_statement, programming_language
) -> str:
    """Adds the exercise context to the prompt
    :param exercise_title: The exercise title
    :param problem_statement: The problem statement
    :param programming_language: The programming language
    """
    return f"""
    ## Exercise Context
    - **Exercise Title:** {exercise_title.replace("{", "{{").replace("}", "}}")}
    - **Problem Statement:** {problem_statement.replace("{", "{{").replace("}", "}}")}
    - **Programming Language:** {programming_language}
    """


def convert_chat_history_to_str(chat_history: List[PyrisMessage]) -> str:
    """
    Converts the chat history to a string
    :param chat_history: The chat history
    :return: The chat history as a string
    """

    def map_message_role(role: IrisMessageRole) -> str:
        if role == IrisMessageRole.SYSTEM:
            return "System"
        elif role == IrisMessageRole.ASSISTANT:
            return "AI Tutor"
        elif role == IrisMessageRole.USER:
            return "Student"
        else:
            return "Unknown"

    return "\n\n".join(
        [
            f"{map_message_role(message.sender)} {"" if not message.sent_at else f"at {message.sent_at.strftime(
                "%Y-%m-%d %H:%M:%S")}"}: {message.contents[0].text_content}"
            for message in chat_history
        ]
    )


class ExerciseChatAgentPipeline(Pipeline):
    """Exercise chat agent pipeline that answers exercises related questions from students."""

    llm_big: IrisLangchainChatModel
    llm_small: IrisLangchainChatModel
    pipeline: Runnable
    callback: ExerciseChatStatusCallback
    suggestion_pipeline: InteractionSuggestionPipeline
    code_feedback_pipeline: CodeFeedbackPipeline
    prompt: ChatPromptTemplate
    variant: str
    event: str | None

    def __init__(
        self,
        callback: ExerciseChatStatusCallback,
        variant: str = "default",
        event: str | None = None,
    ):
        super().__init__(implementation_id="exercise_chat_pipeline")
        # Set the langchain chat model
        completion_args = CompletionArguments(temperature=0.5, max_tokens=2000)
        self.llm_big = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(
                    gpt_version_equivalent=4.5,
                ),
            ),
            completion_args=completion_args,
        )
        self.llm_small = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(
                    gpt_version_equivalent=4.25,
                ),
            ),
            completion_args=completion_args,
        )
        self.variant = variant
        self.event = event
        self.callback = callback

        # Create the pipelines
        self.db = VectorDatabase()
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant="exercise")
        self.retriever = LectureRetrieval(self.db.client)
        self.reranker_pipeline = RerankerPipeline()
        self.code_feedback_pipeline = CodeFeedbackPipeline()
        self.pipeline = self.llm_big | JsonOutputParser()
        self.citation_pipeline = CitationPipeline()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm_big={self.llm_big}, llm_small={self.llm_small})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm_big={self.llm_big}, llm_small={self.llm_small})"

    @traceable(name="Exercise Chat Agent Pipeline")
    def __call__(self, dto: ExerciseChatPipelineExecutionDTO):
        """
        Runs the pipeline
        :param dto:  execution data transfer object
        :param kwargs: The keyword arguments
        """

        def get_submission_details() -> dict:
            """
            # Submission Details Retrieval Tool

            ## Purpose
            Fetch key information about a student's code submission for context and evaluation.

            ## Retrieved Information
            - submission_date: Submission timing
            - is_practice: Practice or graded attempt
            - build_failed: Build process status
            - latest_result: Most recent evaluation outcome


            """
            self.callback.in_progress("Reading submission details...")
            if not dto.submission:
                return {
                    field: f"No {field.replace('_', ' ')} is provided"
                    for field in [
                        "submission_date",
                        "is_practice",
                        "build_failed",
                        "latest_result",
                    ]
                }

            getter = attrgetter("date", "is_practice", "build_failed", "latest_result")
            values = getter(dto.submission)
            keys = ["submission_date", "is_practice", "build_failed", "latest_result"]

            return {
                key: (
                    str(value)
                    if value is not None
                    else f"No {key.replace('_', ' ')} is provided"
                )
                for key, value in zip(keys, values)
            }

        def get_additional_exercise_details() -> dict:
            """
            # Additional Exercise Details Tool

            ## Purpose
            Retrieve time-related information about the exercise for context and deadline awareness.

            ## Retrieved Information
            - start_date: Exercise commencement
            - end_date: Exercise deadline
            - due_date_over: Boolean indicating if the deadline has passed

            """
            self.callback.in_progress("Reading exercise details...")
            current_time = datetime.now(tz=pytz.UTC)
            return {
                "start_date": (
                    dto.exercise.start_date
                    if dto.exercise
                    else "No start date provided"
                ),
                "end_date": (
                    dto.exercise.end_date if dto.exercise else "No end date provided"
                ),
                "due_date_over": (
                    dto.exercise.end_date < current_time
                    if dto.exercise.end_date
                    else "No end date provided"
                ),
            }

        def get_build_logs_analysis_tool() -> str:
            """
            # Build Logs Analysis Tool

            ## Purpose
            Analyze CI/CD build logs for debugging and code quality feedback.

            ## Retrieved Information
            - Build status (successful or failed)
            - If failed:
              - Error messages
              - Warning messages
              - Timestamps for log entries


            """
            self.callback.in_progress("Analyzing build logs ...")
            if not dto.submission:
                return "No build logs available."
            build_failed = dto.submission.build_failed
            build_logs = dto.submission.build_log_entries
            logs = (
                "The build was successful."
                if not build_failed
                else (
                    "\n".join(
                        str(log) for log in build_logs if "~~~~~~~~~" not in log.message
                    )
                )
            )
            return logs

        def get_feedbacks() -> str:
            """
            # Get Feedbacks Tool
            ## Purpose
            Retrieve and analyze automated test feedback from the CI/CD pipeline.

            ## Retrieved Information
            For each feedback item:
            - Test case name
            - Credits awarded
            - Text feedback


            """
            self.callback.in_progress("Analyzing feedbacks ...")
            if not dto.submission:
                return "No feedbacks available."
            feedbacks = dto.submission.latest_result.feedbacks
            feedback_list = (
                "\n".join(
                    [
                        "Case: {}. Credits: {}. Info: {}".format(
                            feedback.test_case_name, feedback.credits, feedback.text
                        )
                        for feedback in feedbacks
                    ]
                )
                if feedbacks
                else "No feedbacks."
            )
            return feedback_list

        def repository_files() -> str:
            """
            # Repository Files Tool

            ## Purpose
            List files in the student's code submission repository.

            ## Retrieved Information
            - File names in the repository

            ## Usage Guidelines
            1. Use before examining file contents to understand submission structure.
            2. Check for expected files based on exercise requirements.
            3. Identify missing or unexpected files quickly.
            4. Guide discussions about file organization and project structure.

            ## Key Points
            - Helps assess completeness of submission.
            - Useful for spotting potential issues (e.g., misplaced files).
            - Informs which files to examine in detail next.


            """
            self.callback.in_progress("Checking repository content ...")
            if not dto.submission:
                return "No repository content available."
            repository = dto.submission.repository
            file_list = "\n------------\n".join(
                ["- {}".format(file_name) for (file_name, _) in repository.items()]
            )
            return file_list

        def file_lookup(file_path: str) -> str:
            """
            # File Lookup Tool

            ## Purpose
            Retrieve content of a specific file from the student's code repository.

            ## Input
            - file_path: Path of the file to retrieve

            ## Retrieved Information
            - File content if found, or "File not found" message

            ## Usage Guidelines
            1. Use after identifying relevant files with the repository_files tool.
            2. Examine file contents for code review, bug identification, or style assessment.
            3. Compare file content with exercise requirements or expected implementations.
            4. If a file is not found, consider if it's a required file or a naming issue.

            ## Key Points
            - This tool should only be used after the repository_files tool has been used to identify
            the files in the repository. That way, you can have the correct file path to look up the file content.
            - Essential for detailed code analysis and feedback.
            - Helps in assessing code quality, correctness, and adherence to specifications.
            - Use in conjunction with exercise details for context-aware evaluation.


            """
            self.callback.in_progress(f"Looking into file {file_path} ...")
            if not dto.submission:
                return (
                    "No repository content available. File content cannot be retrieved."
                )

            repository = dto.submission.repository
            if file_path in repository:
                return "{}:\n{}\n".format(file_path, repository[file_path])
            return "File not found or does not exist in the repository."

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
                chat_history=chat_history,
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

        iris_initial_system_prompt = tell_iris_initial_system_prompt
        chat_history_exists_prompt = tell_chat_history_exists_prompt
        no_chat_history_prompt = tell_no_chat_history_prompt
        format_reminder_prompt = tell_format_reminder_prompt

        try:
            logger.info("Running exercise chat pipeline...")
            query = dto.chat_history[-1] if dto.chat_history else None
            # Check if the latest message is not from the student set the query to None
            if query and query.sender != IrisMessageRole.USER:
                query = None

            # if the query is None, get the last 5 messages from the chat history, including the latest message.
            # otherwise exclude the latest message from the chat history.

            chat_history = (
                dto.chat_history[-5:] if query is None else dto.chat_history[-6:-1]
            )

            # Set up the initial prompt
            initial_prompt_with_date = iris_initial_system_prompt.replace(
                "{current_date}",
                datetime.now(tz=pytz.UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )
            # Determine the agent prompt based on the event.
            # An event parameter might indicates that a
            # specific event is triggered, such as a build failure or stalled progress.
            if self.event == "build_failed":
                agent_prompt = tell_build_failed_system_prompt
            elif self.event == "progress_stalled":
                agent_prompt = tell_progress_stalled_system_prompt
            else:
                agent_prompt = (
                    tell_begin_agent_prompt
                    if query is not None
                    else no_chat_history_prompt
                )

            problem_statement: str = dto.exercise.problem_statement
            exercise_title: str = dto.exercise.name
            programming_language = dto.exercise.programming_language.lower()

            params = {}

            if len(chat_history) > 0 and query is not None and self.event is None:
                # Add the conversation to the prompt
                chat_history_messages = convert_chat_history_to_str(chat_history)
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        SystemMessage(
                            initial_prompt_with_date
                            + "\n"
                            + add_exercise_context_to_prompt(
                                exercise_title, problem_statement, programming_language
                            )
                            + "\n"
                            + agent_prompt
                            + "\n"
                            + format_reminder_prompt,
                        ),
                        HumanMessage(chat_history_exists_prompt),
                        HumanMessage(chat_history_messages),
                        HumanMessage("Consider the student's newest and latest input:"),
                        convert_iris_message_to_langchain_human_message(query),
                        ("placeholder", "{agent_scratchpad}"),
                    ]
                )
            else:
                if query is not None and self.event is None:
                    self.prompt = ChatPromptTemplate.from_messages(
                        [
                            SystemMessage(
                                initial_prompt_with_date
                                + "\n"
                                + add_exercise_context_to_prompt(
                                    exercise_title,
                                    problem_statement,
                                    programming_language,
                                )
                                + agent_prompt
                                + "\n"
                                + format_reminder_prompt,
                            ),
                            HumanMessage(
                                "Consider the student's newest and latest input:"
                            ),
                            convert_iris_message_to_langchain_human_message(query),
                            ("placeholder", "{agent_scratchpad}"),
                        ]
                    )
                else:
                    self.prompt = ChatPromptTemplate.from_messages(
                        [
                            SystemMessage(
                                initial_prompt_with_date
                                + "\n"
                                + add_exercise_context_to_prompt(
                                    exercise_title,
                                    problem_statement,
                                    programming_language,
                                )
                                + agent_prompt
                                + "\n"
                                + format_reminder_prompt,
                            ),
                            ("placeholder", "{agent_scratchpad}"),
                        ]
                    )
            tool_list = [
                get_submission_details,
                get_additional_exercise_details,
                get_build_logs_analysis_tool,
                get_feedbacks,
                repository_files,
                file_lookup,
            ]
            if self.should_allow_lecture_tool(dto.course.id):
                tool_list.append(lecture_content_retrieval)
            tools = generate_structured_tools_from_functions(tool_list)
            agent = create_tool_calling_agent(
                llm=self.llm_big, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)
            self.callback.in_progress()
            out = None
            for step in agent_executor.iter(params):
                self._append_tokens(
                    self.llm_big.tokens, PipelineEnum.IRIS_CHAT_EXERCISE_AGENT_MESSAGE
                )
                if step.get("output", None):
                    out = step["output"]

            try:
                self.callback.in_progress("Refining response...")
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        SystemMessagePromptTemplate.from_template(guide_system_prompt),
                    ]
                )

                guide_response = (
                    self.prompt | self.llm_small | StrOutputParser()
                ).invoke(
                    {
                        "response": out,
                    }
                )
                self._append_tokens(
                    self.llm_small.tokens, PipelineEnum.IRIS_CHAT_EXERCISE_AGENT_MESSAGE
                )
                if "!ok!" in guide_response:
                    print("Response is ok and not rewritten!!!")
                else:
                    out = guide_response
                    print("Response is rewritten.")

                self.callback.done(
                    "Response created", final_result=out, tokens=self.tokens
                )
            except Exception as e:
                logger.error(
                    "An error occurred while running the course chat interaction suggestion pipeline",
                    exc_info=e,
                )
                traceback.print_exc()
                self.callback.error("Error in refining response")
            try:
                if out:
                    suggestion_dto = InteractionSuggestionPipelineExecutionDTO()
                    suggestion_dto.chat_history = dto.chat_history
                    suggestion_dto.last_message = out
                    suggestions = self.suggestion_pipeline(suggestion_dto)
                    if self.suggestion_pipeline.tokens is not None:
                        tokens = [self.suggestion_pipeline.tokens]
                    else:
                        tokens = []
                    self.callback.done(
                        final_result=None, suggestions=suggestions, tokens=tokens
                    )
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
                "An error occurred while running the course chat pipeline", exc_info=e
            )
            traceback.print_exc()
            self.callback.error(
                "An error occurred while running the course chat pipeline."
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
