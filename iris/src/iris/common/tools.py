import typing
from datetime import datetime
from typing import Callable, List, Optional, Union

import pytz

from ..domain import CourseChatPipelineExecutionDTO
from ..retrieval.faq_retrieval import FaqRetrieval
from ..retrieval.faq_retrieval_utils import format_faqs
from ..retrieval.lecture.lecture_retrieval import LectureRetrieval
from ..web.status.status_update import CourseChatStatusCallback
from .mastery_utils import get_mastery


def datetime_to_string(dt: Optional[datetime]) -> str:
    """
    Convert a datetime to a formatted string.

    Args:
        dt (Optional[datetime]): The datetime to convert.

    Returns:
        str: Formatted datetime or 'No date provided'.
    """
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_tool_get_exercise_list(
    dto: CourseChatPipelineExecutionDTO, callback: CourseChatStatusCallback
) -> Callable[[], list[dict]]:
    """
    Create a tool that retrieves the exercise list.

    Args:
        dto (CourseChatPipelineExecutionDTO): Execution DTO containing course data.
        callback (CourseChatStatusCallback): Callback for status updates.

    Returns:
        Callable[[], list[dict]]: Function that returns the list of exercises.
    """

    def get_exercise_list() -> list[dict]:
        """
        Get the list of exercises in the course.
        Use this if the student asks you about an exercise.
        Note: The exercise contains a list of submissions (timestamp and score) of this student so you
        can provide additional context regarding their progress and tendencies over time.
        Also, ensure to use the provided current date and time and compare it to the start date and due date etc.
        Do not recommend that the student should work on exercises with a past due date.
        The submissions array tells you about the status of the student in this exercise:
        You see when the student submitted the exercise and what score they got.
        A 100% score means the student solved the exercise correctly and completed it.

        Returns:
            list[dict]: List of exercise data without problem statements.
        """
        callback.in_progress("Reading exercise list ...")
        current_time = datetime.now(tz=pytz.UTC)
        exercises = []
        for exercise in dto.course.exercises:
            exercise_dict = exercise.model_dump()
            exercise_dict["due_date_over"] = (
                exercise.due_date < current_time if exercise.due_date else None
            )
            # remove the problem statement from the exercise dict
            exercise_dict.pop("problem_statement", None)
            exercises.append(exercise_dict)
        return exercises

    return get_exercise_list


def create_tool_get_exercise_problem_statement(
    dto: CourseChatPipelineExecutionDTO, callback: CourseChatStatusCallback
) -> Callable[[int], str]:
    """
    Create a tool that retrieves an exercise problem statement.

    Args:
        dto (CourseChatPipelineExecutionDTO): Execution DTO containing course data.
        callback (CourseChatStatusCallback): Callback for status updates.

    Returns:
        Callable[[int], str]: Function that returns the problem statement.
    """

    def get_exercise_problem_statement(exercise_id: int) -> str:
        """
        Get the problem statement of the exercise with the given ID.
        Use this if the student asks you about the problem statement of an exercise or if you need
        to know more about the content of an exercise to provide more informed advice.
        Important: You have to pass the correct exercise ID here.
        DO IT ONLY IF YOU KNOW THE ID DEFINITELY. NEVER GUESS THE ID.
        Note: This operation is idempotent. Repeated calls with the same ID will return the same output.
        You can only use this if you first queried the exercise list and looked up the ID of the exercise.

        Args:
            exercise_id (int): The ID of the exercise.

        Returns:
            str: The problem statement or an error message if not found.
        """
        callback.in_progress(
            f"Reading exercise problem statement (id: {exercise_id}) ..."
        )
        exercise = next(
            (ex for ex in dto.course.exercises if ex.id == exercise_id), None
        )
        if exercise:
            return exercise.problem_statement or "No problem statement provided"
        else:
            return "Exercise not found"

    return get_exercise_problem_statement


def create_tool_get_course_details(
    dto: CourseChatPipelineExecutionDTO, callback: CourseChatStatusCallback
) -> Callable[[], dict]:
    """
    Create a tool that retrieves course details.

    Args:
        dto (CourseChatPipelineExecutionDTO): Execution DTO containing course data.
        callback (CourseChatStatusCallback): Callback for status updates.

    Returns:
        Callable[[], dict]: Function that returns course details.
    """

    def get_course_details() -> dict:
        """
        Get the following course details: course name, course description, programming language, course start date,
        and course end date.

        Returns:
            dict: Course name, description, programming language, start and end dates.
        """
        callback.in_progress("Reading course details ...")
        return {
            "course_name": (dto.course.name if dto.course else "No course provided"),
            "course_description": (
                dto.course.description
                if dto.course and dto.course.description
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

    return get_course_details


def create_tool_get_student_exercise_metrics(
    dto: CourseChatPipelineExecutionDTO, callback: CourseChatStatusCallback
) -> Callable[[typing.List[int]], Union[dict[int, dict], str]]:
    """
    Create a tool that retrieves student exercise metrics.

    Args:
        dto (CourseChatPipelineExecutionDTO): Execution DTO containing metrics.
        callback (CourseChatStatusCallback): Callback for status updates.

    Returns:
        Callable[[List[int]], Union[dict[int, dict], str]]: Function to get metrics.
    """

    def get_student_exercise_metrics(
        exercise_ids: typing.List[int],
    ) -> Union[dict[int, dict], str]:
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

        Args:
            exercise_ids (List[int]): List of exercise IDs to fetch metrics for.

        Returns:
            Union[dict[int, dict], str]: Metrics per exercise ID or error message.
        """
        callback.in_progress("Checking your statistics ...")
        if not dto.metrics or not dto.metrics.exercise_metrics:
            return "No data available!! Do not requery."
        metrics = dto.metrics.exercise_metrics
        if metrics.average_score and any(
            exercise_id in metrics.average_score for exercise_id in exercise_ids
        ):
            return {
                exercise_id: {
                    "global_average_score": metrics.average_score[exercise_id],
                    "score_of_student": metrics.score.get(exercise_id, None),
                    "global_average_latest_submission": metrics.average_latest_submission.get(
                        exercise_id, None
                    ),
                    "latest_submission_of_student": metrics.latest_submission.get(
                        exercise_id, None
                    ),
                }
                for exercise_id in exercise_ids
                if exercise_id in metrics.average_score
            }
        else:
            return "No data available! Do not requery."

    return get_student_exercise_metrics


def create_tool_get_competency_list(
    dto: CourseChatPipelineExecutionDTO, callback: CourseChatStatusCallback
) -> Callable[[], list]:
    """
    Create a tool that retrieves the competency list.

    Args:
        dto (CourseChatPipelineExecutionDTO): Execution DTO containing competencies.
        callback (CourseChatStatusCallback): Callback for status updates.

    Returns:
        Callable[[], list]: Function that returns competencies with metrics.
    """

    def get_competency_list() -> list:
        """
        Get the list of competencies in the course.
        Exercises might be associated with competencies. A competency is a skill or knowledge that a student
        should have after completing the course, and instructors may add lectures and exercises
        to these competencies.
        You can use this if the students asks you about a competency, or if you want to provide additional context
        regarding their progress overall or in a specific area.
        A competency has the following attributes: name, description, taxonomy, soft due date, optional,
        and mastery threshold.
        The response may include metrics for each competency, such as progress and mastery (0% - 100%).
        These are system-generated.
        The judgment of learning (JOL) values indicate the self-reported mastery by the student (0 - 5, 5 star).
        The object describing it also indicates the system-computed mastery at the time when the student
        added their JoL assessment.

        Returns:
            list: Competencies with info, exercise IDs, progress, mastery, and JOL.
        """
        callback.in_progress("Reading competency list ...")
        if not dto.metrics or not dto.metrics.competency_metrics:
            return dto.course.competencies
        competency_metrics = dto.metrics.competency_metrics
        return [
            {
                "info": competency_metrics.competency_information.get(comp, None),
                "exercise_ids": competency_metrics.exercises.get(comp, []),
                "progress": competency_metrics.progress.get(comp, 0),
                "mastery": get_mastery(
                    competency_metrics.progress.get(comp, 0),
                    competency_metrics.confidence.get(comp, 0),
                ),
                "judgment_of_learning": (
                    competency_metrics.jol_values.get[comp].json()
                    if competency_metrics.jol_values
                    and comp in competency_metrics.jol_values
                    else None
                ),
            }
            for comp in competency_metrics.competency_information
        ]

    return get_competency_list


def create_tool_lecture_content_retrieval(
    lecture_retriever: LectureRetrieval,
    dto: CourseChatPipelineExecutionDTO,
    callback: CourseChatStatusCallback,
    query_text: str,
    history: List,
    lecture_content_storage: dict,
) -> Callable[[], str]:
    """
    Create a tool that retrieves lecture content using RAG.

    Args:
        lecture_retriever (LectureRetrieval): Lecture retrieval instance.
        dto (CourseChatPipelineExecutionDTO): Execution DTO with course data.
        callback (CourseChatStatusCallback): Callback for status updates.
        query_text (str): The student's query text.
        history (List): Chat history messages.
        lecture_content_storage (dict): Storage for retrieved content.

    Returns:
        Callable[[], str]: Function that returns lecture content string.
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
            str: Concatenated lecture slide, transcription, and segment content.
        """
        callback.in_progress("Retrieving lecture content ...")
        lecture_content = lecture_retriever(
            query=query_text,
            course_id=dto.course.id,
            chat_history=history,
            lecture_id=None,
            lecture_unit_id=None,
            base_url=dto.settings.artemis_base_url,
        )

        # Store the lecture content for later use (e.g., citation pipeline)
        lecture_content_storage["content"] = lecture_content

        result = "Lecture slide content:\n"
        for paragraph in lecture_content.lecture_unit_page_chunks:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
            )

        result += "Lecture transcription content:\n"
        for paragraph in lecture_content.lecture_transcriptions:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_text}---\n\n"
            )

        result += "Lecture segment content:\n"
        for paragraph in lecture_content.lecture_unit_segments:
            result += (
                f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
                f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_summary}---\n\n"
            )

        return result

    return lecture_content_retrieval


def create_tool_faq_content_retrieval(
    faq_retriever: FaqRetrieval,
    dto: CourseChatPipelineExecutionDTO,
    callback: CourseChatStatusCallback,
    query_text: str,
    history: List,
    faq_storage: dict,
) -> Callable[[], str]:
    """
    Create a tool that retrieves FAQ content using RAG.

    Args:
        faq_retriever (FaqRetrieval): FAQ retrieval instance.
        dto (CourseChatPipelineExecutionDTO): Execution DTO with course data.
        callback (CourseChatStatusCallback): Callback for status updates.
        query_text (str): The student's query text.
        history (List): Chat history messages.
        faq_storage (dict): Storage for retrieved FAQs.

    Returns:
        Callable[[], str]: Function that returns formatted FAQ content.
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
            str: Formatted string containing relevant FAQ answers.
        """
        callback.in_progress("Retrieving faq content ...")
        retrieved_faqs = faq_retriever(
            chat_history=history,
            student_query=query_text,
            result_limit=10,
            course_name=dto.course.name,
            course_id=dto.course.id,
            base_url=dto.settings.artemis_base_url,
        )

        # Store the retrieved FAQs for later use (e.g., citation pipeline)
        faq_storage["faqs"] = retrieved_faqs

        result = format_faqs(retrieved_faqs)
        return result

    return faq_content_retrieval
