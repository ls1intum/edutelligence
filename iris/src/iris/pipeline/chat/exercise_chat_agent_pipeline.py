import logging
import traceback
from datetime import datetime
from operator import attrgetter
from typing import List

import pytz
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import Runnable
from langsmith import traceable
from weaviate.collections.classes.filters import Filter

from ...common.message_converters import (
    convert_iris_message_to_langchain_human_message,
)
from ...common.pipeline_enum import PipelineEnum
from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain import ExerciseChatPipelineExecutionDTO, FeatureDTO
from ...domain.chat.interaction_suggestion_dto import (
    InteractionSuggestionPipelineExecutionDTO,
)
from ...domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
)
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from ...llm.external.model import LanguageModel
from ...llm.langchain import IrisLangchainChatModel
from ...retrieval.faq_retrieval import FaqRetrieval
from ...retrieval.faq_retrieval_utils import format_faqs, should_allow_faq_tool
from ...retrieval.lecture.lecture_retrieval import LectureRetrieval
from ...vector_database.database import VectorDatabase
from ...vector_database.lecture_unit_schema import LectureUnitSchema
from ...web.status.status_update import ExerciseChatStatusCallback
from ..pipeline import Pipeline
from ..prompts.iris_exercise_chat_agent_prompts import (
    guide_system_prompt,
    tell_begin_agent_prompt,
    tell_build_failed_system_prompt,
    tell_chat_history_exists_prompt,
    tell_format_reminder_prompt,
    tell_iris_initial_system_prompt,
    tell_no_chat_history_prompt,
    tell_progress_stalled_system_prompt,
)
from ..shared.citation_pipeline import CitationPipeline, InformationType
from ..shared.utils import (
    filter_variants_by_available_models,
    format_custom_instructions,
    generate_structured_tools_from_functions,
)
from .code_feedback_pipeline import CodeFeedbackPipeline
from .interaction_suggestion_pipeline import InteractionSuggestionPipeline

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

    llm: IrisLangchainChatModel
    llm_small: IrisLangchainChatModel
    pipeline: Runnable
    callback: ExerciseChatStatusCallback
    suggestion_pipeline: InteractionSuggestionPipeline
    code_feedback_pipeline: CodeFeedbackPipeline
    prompt: ChatPromptTemplate
    variant: str
    event: str | None
    retrieved_faqs: List[dict] = None
    lecture_content: LectureRetrievalDTO = None

    def __init__(
        self,
        callback: ExerciseChatStatusCallback,
        variant: str = "default",
        event: str | None = None,
    ):
        super().__init__(implementation_id="exercise_chat_pipeline")

        # Set the langchain chat model
        completion_args = CompletionArguments(temperature=0.5, max_tokens=2000)

        if variant == "advanced":
            model = "gpt-4.1"
            model_small = "gpt-4.1-mini"
        else:
            model = "gpt-4.1-mini"
            model_small = "gpt-4.1-nano"

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model),
            completion_args=completion_args,
        )

        self.llm_small = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(version=model_small),
            completion_args=completion_args,
        )
        self.event = event
        self.callback = callback

        # Create the pipelines
        self.db = VectorDatabase()
        self.suggestion_pipeline = InteractionSuggestionPipeline(variant="exercise")
        self.lecture_retriever = LectureRetrieval(self.db.client)
        self.faq_retriever = FaqRetrieval(self.db.client)
        self.code_feedback_pipeline = CodeFeedbackPipeline()
        self.pipeline = self.llm | JsonOutputParser()
        self.citation_pipeline = CitationPipeline()
        self.tokens = []

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm}, llm_small={self.llm_small})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm}, llm_small={self.llm_small})"

    @classmethod
    def get_variants(cls, available_llms: List[LanguageModel]) -> List[FeatureDTO]:
        variant_specs = [
            (
                ["gpt-4.1-mini", "gpt-4.1-nano"],
                FeatureDTO(
                    id="default",
                    name="Default",
                    description="Uses a smaller model for faster and cost-efficient responses.",
                ),
            ),
            (
                ["gpt-4.1", "gpt-4.1-mini"],
                FeatureDTO(
                    id="advanced",
                    name="Advanced",
                    description="Uses a larger chat model, balancing speed and quality.",
                ),
            ),
        ]

        return filter_variants_by_available_models(
            available_llms, variant_specs, pipeline_name="ExerciseChatAgentPipeline"
        )

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
                    field: f"No {field.replace("_", " ")} is provided"
                    for field in [
                        "submission_date",
                        "is_practice",
                        "build_failed",
                        "latest_result",
                    ]
                }

            getter = attrgetter("date", "is_practice", "build_failed", "latest_result")
            values = getter(dto.submission)
            keys = [
                "submission_date",
                "is_practice",
                "build_failed",
                "latest_result",
            ]

            return {
                key: (
                    str(value)
                    if value is not None
                    else f"No {key.replace("_", " ")} is provided"
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
                        f"Case: {feedback.test_case_name}. Credits: {feedback.credits}. Info: {feedback.text}"
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
                [f"- {file_name}" for (file_name, _) in repository.items()]
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
                return f"{file_path}:\n{repository[file_path]}\n"
            return "File not found or does not exist in the repository."

        def lecture_content_retrieval() -> str:
            """
            Retrieve content from indexed lecture content.
            This will run a RAG retrieval based on the chat history on the indexed lecture slides,
            the indexed lecture transcriptions and the indexed lecture segments,
            which are summaries of the lecture slide content and lecture transcription content from one slide a
            nd return the most relevant paragraphs.
            Use this if you think it can be useful to answer the student's question, or if the student explicitly asks
            a question about the lecture content or slides.
            Only use this once.
            """
            self.callback.in_progress("Retrieving lecture content ...")
            self.lecture_content = self.lecture_retriever(
                query=query.contents[0].text_content,
                course_id=dto.course.id,
                chat_history=chat_history,
                lecture_id=None,
                lecture_unit_id=None,
                base_url=dto.settings.artemis_base_url,
            )

            result = "Lecture slide content:\n"
            for paragraph in self.lecture_content.lecture_unit_page_chunks:
                lct = (
                    f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                    f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
                )
                result += lct

            result += "Lecture transcription content:\n"
            for paragraph in self.lecture_content.lecture_transcriptions:
                transcription = (
                    f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                    f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_text}---\n\n"
                )
                result += transcription

            result += "Lecture segment content:\n"
            for paragraph in self.lecture_content.lecture_unit_segments:
                segment = (
                    f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                    f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_summary}---\n\n"
                )
                result += segment
            return result

        def faq_content_retrieval() -> str:
            """
            Use this tool to retrieve information from indexed FAQs.
            It is suitable when no other tool fits, it is a common question or the question is frequently asked,
            or the question could be effectively answered by an FAQ. Also use this if the question is explicitly
            organizational and course-related. An organizational question about the course might be
            "What is the course structure?" or "How do I enroll?" or exam related content like "When is the exam".
            The tool performs a RAG retrieval based on the chat history to find the most relevant FAQs.
            Each FAQ follows this format: FAQ ID, FAQ Question, FAQ Answer.
            Respond to the query concisely and solely using the answer from the relevant FAQs.
            This tool should only be used once per query.
            """
            self.callback.in_progress("Retrieving faq content ...")
            self.retrieved_faqs = self.faq_retriever(
                chat_history=chat_history,
                student_query=query.contents[0].text_content,
                result_limit=10,
                course_name=dto.course.name,
                course_id=dto.course.id,
                base_url=dto.settings.artemis_base_url,
            )

            result = format_faqs(self.retrieved_faqs)
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

            custom_instructions = format_custom_instructions(
                custom_instructions=dto.custom_instructions
            )

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
                                exercise_title,
                                problem_statement,
                                programming_language,
                            )
                            + "\n"
                            + agent_prompt
                            + "\n"
                            + custom_instructions
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
                                + custom_instructions
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
                                + custom_instructions
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

            if should_allow_faq_tool(self.db, dto.course.id):
                tool_list.append(faq_content_retrieval)

            tools = generate_structured_tools_from_functions(tool_list)
            agent = create_tool_calling_agent(
                llm=self.llm, tools=tools, prompt=self.prompt
            )
            agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=False)
            self.callback.in_progress("Thinking ...")
            out = None
            for step in agent_executor.iter(params):
                self._append_tokens(
                    self.llm.tokens,
                    PipelineEnum.IRIS_CHAT_EXERCISE_AGENT_MESSAGE,
                )
                if step.get("output", None):
                    out = step["output"]

            try:
                self.callback.in_progress("Refining response ...")
                self.prompt = ChatPromptTemplate.from_messages(
                    [
                        SystemMessagePromptTemplate.from_template(guide_system_prompt),
                        HumanMessage(out),
                    ]
                )

                guide_response = (
                    self.prompt | self.llm_small | StrOutputParser()
                ).invoke(
                    {
                        "problem": problem_statement,
                    }
                )
                self._append_tokens(
                    self.llm.tokens,
                    PipelineEnum.IRIS_CHAT_EXERCISE_AGENT_MESSAGE,
                )
                if "!ok!" in guide_response:
                    print("Response is ok and not rewritten!!!")
                else:
                    print("ORIGINAL RESPONSE: " + out)
                    out = guide_response
                    print("NEW RESPONSE: " + out)
                    print("Response is rewritten.")

                if self.retrieved_faqs:
                    self.callback.in_progress("Augmenting response ...")
                    out = self.citation_pipeline(
                        self.retrieved_faqs,
                        out,
                        InformationType.FAQS,
                        variant=self.variant,
                        base_url=dto.settings.artemis_base_url,
                    )

                if self.lecture_content:
                    self.callback.in_progress("Augmenting response ...")
                    out = self.citation_pipeline(
                        self.lecture_content,
                        out,
                        InformationType.PARAGRAPHS,
                        variant=self.variant,
                        base_url=dto.settings.artemis_base_url,
                    )
                self.tokens.extend(self.citation_pipeline.tokens)

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
                        final_result=None,
                        suggestions=suggestions,
                        tokens=tokens,
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
                "An error occurred while running the exercise chat pipeline",
                exc_info=e,
            )
            traceback.print_exc()
            self.callback.error(
                "An error occurred while running the exercise chat pipeline."
            )

    def should_allow_lecture_tool(self, course_id: int) -> bool:
        """
        Checks if there are indexed lectures for the given course

        :param course_id: The course ID
        :return: True if there are indexed lectures for the course, False otherwise
        """
        if course_id:
            # Fetch the first object that matches the course ID with the language property
            result = self.db.lecture_units.query.fetch_objects(
                filters=Filter.by_property(LectureUnitSchema.COURSE_ID.value).equal(
                    course_id
                ),
                limit=1,
                return_properties=[LectureUnitSchema.COURSE_NAME.value],
            )
            return len(result.objects) > 0
        return False
