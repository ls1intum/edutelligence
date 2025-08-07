import json
import logging
import re
from typing import List

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)
from iris.retrieval.faq_retrieval import FaqRetrieval
from iris.retrieval.faq_retrieval_utils import format_faqs
from iris.retrieval.lecture.lecture_retrieval import LectureRetrieval
from iris.vector_database.database import VectorDatabase

logger = logging.getLogger(__name__)


class ChannelType:
    PROGRAMMING_EXERCISE = "programming_exercise"
    TEXT_EXERCISE = "text_exercise"
    LECTURE = "lecture"
    GENERAL = "general"


def get_user_query(chat_history: List[PyrisMessage]):
    """
    Extracts the user query from the chat history.
    :param chat_history: List of messages in the chat history.
    :return: The user query as a string.
    """
    if chat_history and chat_history[-1].sender == IrisMessageRole.USER:
        if chat_history[-1].contents:
            return chat_history[-1].contents[0].text_content
        return "User message has no content."
    return "No user query found in chat history."


def get_last_artifact(chat_history: List[PyrisMessage]):
    """
    Extracts the last artifact from the chat history.
    :param chat_history: List of messages in the chat history.
    :return: The last artifact as a string.
    """
    if chat_history:
        for message in reversed(chat_history):
            if message.sender == IrisMessageRole.ARTIFACT:
                if message.contents:
                    return message.contents[0].text_content
                return "Artifact message has no content."
    return "No artifact found in chat history."


def get_chat_history_without_user_query(chat_history: List[PyrisMessage]) -> str:
    """
    Extracts the chat history without the user query.
    :param chat_history: List of messages in the chat history.
    :return: The chat history as a string.
    """
    chat_history_str = "No chat history found."
    if chat_history and chat_history[-1].sender == IrisMessageRole.USER:
        chat_history = chat_history[:-1]
        # remove all TUT_SUG messages because they are not relevant for the prompt
        chat_history = [
            message
            for message in chat_history
            if message.sender != IrisMessageRole.ARTIFACT
        ]
        chat_history_str = "\n".join(
            [
                f"{message.sender.name}: {message.contents[0].text_content if message.contents else "No content"}"
                for message in chat_history
            ]
        )
    return chat_history_str


def extract_html_from_text(text: str):
    html_pattern = re.compile(
        r"(?P<html>(<[^>]+>.*?</[^>]+>)|(&lt;[^&]+&gt;.*?&lt;/[^&]+&gt;))", re.DOTALL
    )
    match = html_pattern.search(text)
    if match:
        return match.group("html").strip()
    else:
        return None


def extract_list_html_from_text(text: str):
    html_pattern = re.compile(
        r"(?P<html><ul>.*?</ul>|&lt;ul&gt;.*?&lt;/ul&gt;)", re.DOTALL
    )
    match = html_pattern.search(text)
    return match.group("html").strip() if match else None


def has_html(text: str):
    """
    Check if the text contains HTML tags.
    :param text: The text to check.
    :return: True if HTML tags are found, False otherwise.
    """
    html_pattern = re.compile(r"<[^>]+>")
    return bool(html_pattern.search(text))


def get_channel_type(dto: CommunicationTutorSuggestionPipelineExecutionDTO) -> str:
    """
    Determines the channel type based on the context of the post.
    :return: The channel type as a string.
    """
    if dto.programming_exercise is not None:
        return ChannelType.PROGRAMMING_EXERCISE
    elif dto.text_exercise is not None:
        return ChannelType.TEXT_EXERCISE
    elif dto.lecture_id is not None:
        return ChannelType.LECTURE
    else:
        return ChannelType.GENERAL


def sort_post_answers(dto):
    """
    Sort the answers of the post by their id
    :param dto: execution data transfer object
    """
    if dto.post is None or dto.post.answers is None:
        return dto
    dto.post.answers.sort(key=lambda x: x.id)
    return dto


def extract_json_substring(input_string):
    start = input_string.find("{")
    end = input_string.rfind("}")
    if start == -1 or end == -1 or start > end:
        raise ValueError("No valid JSON object found in the input string.")
    json_substring = input_string[start : end + 1]
    return json_substring


def escape_json_control_chars(json_str: str) -> str:
    def replace_inside_quotes(match):
        content = match.group(0)
        content = content.replace('"', '"')
        content = content.replace("\n", "\\n").replace("\t", "\\t")
        return content

    return re.sub(r'"(.*?)"', replace_inside_quotes, json_str, flags=re.DOTALL)


def extract_json_from_text(input_string):
    try:
        json_str = extract_json_substring(input_string)
        json_str = escape_json_control_chars(json_str)
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Error parsing JSON: %s | Raw string: %r", e, input_string)
        return None


def lecture_content_retrieval(
    dto: CommunicationTutorSuggestionPipelineExecutionDTO,
    chat_summary: str,
    db: VectorDatabase,
) -> str:
    """
    Retrieve content from indexed lecture content.
    This will run a RAG retrieval based on the chat history on the indexed lecture slides,
    the indexed lecture transcriptions and the indexed lecture segments,
    which are summaries of the lecture slide content and lecture transcription content from one slide
    and return the most relevant paragraphs.
    """

    query = (
        f"I want to understand the following summarized discussion better: {chat_summary}\n. What are the relevant"
        f" lecture slides, transcriptions and segments that I can use to answer the question?"
    )
    lecture_retrieval = LectureRetrieval(db.client)

    try:
        lecture_retrieval_result = lecture_retrieval(
            query=query,
            course_id=dto.course.id,
            chat_history=[],
            lecture_id=dto.lecture_id if dto.lecture_id else None,
        )
    except AttributeError as e:
        return "Error retrieving lecture data: " + str(e)

    result = "Lecture slide content:\n"
    for paragraph in lecture_retrieval_result.lecture_unit_page_chunks:
        lct = (
            f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
            f"Page: {paragraph.page_number}\nContent:\n---{paragraph.page_text_content}---\n\n"
        )
        result += lct

    result += "Lecture transcription content:\n"
    for paragraph in lecture_retrieval_result.lecture_transcriptions:
        transcription = (
            f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
            f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_text}---\n\n"
        )
        result += transcription

    result += "Lecture segment content:\n"
    for paragraph in lecture_retrieval_result.lecture_unit_segments:
        segment = (
            f"Lecture: {paragraph.lecture_name}, Unit: {paragraph.lecture_unit_name}, "
            f"Page: {paragraph.page_number}\nContent:\n---{paragraph.segment_summary}---\n\n"
        )
        result += segment
    return result


def faq_content_retrieval(
    db: VectorDatabase,
    chat_summary: str,
    dto: CommunicationTutorSuggestionPipelineExecutionDTO,
) -> str:
    """
    Retrieve content from indexed FAQs.
    This will run a RAG retrieval based on the chat history and the user query on the indexed FAQs,
    which are stored in the database, and return the most relevant FAQs.
    :param db: The vector database client.
    :param chat_summary: The summarized discussion that needs further clarification.
    :param dto: The data transfer object containing course information and settings.
    :return: A formatted string containing the relevant FAQs.
    """
    query = (
        f"I want to understand the following summarized discussion better: {chat_summary}\n. Could you provide me"
        f" some additional information?"
    )
    faq_retriever = FaqRetrieval(db.client)
    chat_history = _filter_artifact_messages(dto.chat_history)
    retrieved_faqs = faq_retriever(
        chat_history=chat_history,
        student_query=query,
        result_limit=10,
        course_name=dto.course.name,
        course_id=dto.course.id,
        base_url=dto.settings.artemis_base_url,
    )

    result = format_faqs(retrieved_faqs)
    return result


def _filter_artifact_messages(chat_history: List[PyrisMessage]) -> List[PyrisMessage]:
    """
    Filter out artifact messages from the chat history.
    :param chat_history: List of messages in the chat history.
    :return: Filtered list of messages without artifact messages.
    """
    return [
        message
        for message in chat_history
        if message.sender != IrisMessageRole.ARTIFACT
    ]
