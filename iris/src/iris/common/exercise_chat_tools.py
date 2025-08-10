"""
Exercise chat tools for the exercise chat agent pipeline.

This module contains tool creation functions for the exercise chat pipeline,
following the builder pattern to accommodate required local variables.
"""

from datetime import datetime
from operator import attrgetter
from typing import Callable, List

import pytz

from ..domain import ExerciseChatPipelineExecutionDTO
from ..domain.data.programming_exercise_dto import ProgrammingExerciseDTO
from ..domain.data.programming_submission_dto import ProgrammingSubmissionDTO
from ..retrieval.faq_retrieval import FaqRetrieval
from ..retrieval.faq_retrieval_utils import format_faqs
from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import ExerciseChatStatusCallback, StatusCallback


def create_tool_get_submission_details(
    submission: ProgrammingSubmissionDTO, callback: StatusCallback
) -> Callable[[], dict]:
    """
    Create a tool that retrieves submission details.

    Args:
        submission: Execution DTO containing submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns submission details.
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

        Returns:
            dict: Dictionary containing submission details.
        """
        callback.in_progress("Reading submission details...")
        if not submission:
            return {
                field: f'No {field.replace("_", " ")} is provided'
                for field in [
                    "submission_date",
                    "is_practice",
                    "build_failed",
                    "latest_result",
                ]
            }

        getter = attrgetter("date", "is_practice", "build_failed", "latest_result")
        values = getter(submission)
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
                else f'No {key.replace("_", " ")} is provided'
            )
            for key, value in zip(keys, values)
        }

    return get_submission_details


def create_tool_get_additional_exercise_details(
    exercise: ProgrammingExerciseDTO, callback: StatusCallback
) -> Callable[[], dict]:
    """
    Create a tool that retrieves additional exercise details.

    Args:
        exercise: Execution DTO containing exercise data.
        callback: Callback for status updates.

    Returns:
        Function that returns exercise details.
    """

    def get_additional_exercise_details() -> dict:
        """
        # Additional Exercise Details Tool

        ## Purpose
        Retrieve time-related information about the exercise for context and deadline awareness.

        ## Retrieved Information
        - start_date: Exercise commencement
        - end_date: Exercise deadline
        - due_date_over: Boolean indicating if the deadline has passed

        Returns:
            dict: Dictionary containing exercise timing details.
        """
        callback.in_progress("Reading exercise details...")
        current_time = datetime.now(tz=pytz.UTC)
        return {
            "start_date": (
                exercise.start_date.isoformat()
                if exercise and exercise.start_date
                else "No start date provided"
            ),
            "end_date": (
                exercise.end_date.isoformat()
                if exercise and exercise.end_date
                else "No end date provided"
            ),
            "due_date_over": (
                exercise.end_date < current_time
                if exercise and exercise.end_date
                else "No end date provided"
            ),
        }

    return get_additional_exercise_details


def create_tool_get_build_logs_analysis(
    submission: ProgrammingSubmissionDTO, callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that analyzes build logs.

    Args:
        submission: Execution DTO containing submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns build logs analysis.
    """

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

        Returns:
            str: Build logs analysis result.
        """
        callback.in_progress("Analyzing build logs ...")
        if not submission:
            return "No build logs available."
        build_failed = submission.build_failed
        build_logs = submission.build_log_entries
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

    return get_build_logs_analysis_tool


def create_tool_get_feedbacks(
    submission: ProgrammingSubmissionDTO, callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that retrieves automated test feedback.

    Args:
        submission: submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns feedback analysis.
    """

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

        Returns:
            str: Formatted feedback information.
        """
        callback.in_progress("Analyzing feedbacks ...")
        if not submission:
            return "No feedbacks available."
        feedbacks = submission.latest_result.feedbacks
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

    return get_feedbacks


def create_tool_repository_files(
    submission: ProgrammingSubmissionDTO, callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that lists repository files.

    Args:
        submission: submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns repository file listing.
    """

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

        Returns:
            str: List of files in the repository.
        """
        callback.in_progress("Checking repository content ...")
        if not submission:
            return "No repository content available."
        repository = submission.repository
        file_list = "\n------------\n".join(
            [f"- {file_name}" for (file_name, _) in repository.items()]
        )
        return file_list

    return repository_files


def create_tool_file_lookup(
    submission: ProgrammingSubmissionDTO, callback: StatusCallback
) -> Callable[[str], str]:
    """
    Create a tool that looks up file content.

    Args:
        submission: Execution DTO containing submission data.
        callback: Callback for status updates.

    Returns:
        Function that returns file content by path.
    """

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

        Args:
            file_path: Path of the file to retrieve.

        Returns:
            str: File content or error message.
        """
        callback.in_progress(f"Looking into file {file_path} ...")
        if not submission:
            return "No repository content available. File content cannot be retrieved."

        repository = submission.repository
        if file_path in repository:
            return f"{file_path}:\n{repository[file_path]}\n"
        return "File not found or does not exist in the repository."

    return file_lookup


def create_tool_lecture_content_retrieval(
    dto: ExerciseChatPipelineExecutionDTO,
    callback: ExerciseChatStatusCallback,
    lecture_retriever: LectureRetrieval,
    query: str,
    chat_history: List,
    lecture_content_storage: dict,
) -> Callable[[], str]:
    """
    Create a tool that retrieves lecture content.

    Args:
        dto: Execution DTO containing course data.
        callback: Callback for status updates.
        lecture_retriever: Lecture retrieval instance.
        query: User query text.
        chat_history: Chat history for context.
        lecture_content_storage: Storage for retrieved content.

    Returns:
        Function that returns lecture content.
    """

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

        Returns:
            str: Retrieved lecture content.
        """
        callback.in_progress("Retrieving lecture content ...")
        lecture_content = lecture_retriever(
            query=query,
            course_id=dto.course.id,
            chat_history=chat_history,
            lecture_id=None,
            lecture_unit_id=None,
            base_url=dto.settings.artemis_base_url,
        )

        # Store for later use in citations
        lecture_content_storage["content"] = lecture_content

        result = "Lecture slide content:\n"
        for paragraph in lecture_content.lecture_unit_page_chunks:
            lct = (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
            )
            result += lct

        result += "Lecture transcription content:\n"
        for paragraph in lecture_content.lecture_transcriptions:
            transcription = (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_text}---\n\n"
            )
            result += transcription

        result += "Lecture segment content:\n"
        for paragraph in lecture_content.lecture_unit_segments:
            segment = (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_summary}---\n\n"
            )
            result += segment
        return result

    return lecture_content_retrieval


def create_tool_faq_content_retrieval(
    dto: ExerciseChatPipelineExecutionDTO,
    callback: ExerciseChatStatusCallback,
    faq_retriever: FaqRetrieval,
    query: str,
    chat_history: List,
    faq_storage: dict,
) -> Callable[[], str]:
    """
    Create a tool that retrieves FAQ content.

    Args:
        dto: Execution DTO containing course data.
        callback: Callback for status updates.
        faq_retriever: FAQ retrieval instance.
        query: User query text.
        chat_history: Chat history for context.
        faq_storage: Storage for retrieved FAQs.

    Returns:
        Function that returns FAQ content.
    """

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

        Returns:
            str: Retrieved FAQ content.
        """
        callback.in_progress("Retrieving faq content ...")
        retrieved_faqs = faq_retriever(
            chat_history=chat_history,
            student_query=query,
            result_limit=10,
            course_name=dto.course.name,
            course_id=dto.course.id,
            base_url=dto.settings.artemis_base_url,
        )

        # Store for later use in citations
        faq_storage["faqs"] = retrieved_faqs

        result = format_faqs(retrieved_faqs)
        return result

    return faq_content_retrieval
