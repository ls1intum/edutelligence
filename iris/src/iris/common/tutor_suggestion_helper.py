import json
import logging
import re
from typing import List

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.communication.communication_tutor_suggestion_pipeline_execution_dto import (
    CommunicationTutorSuggestionPipelineExecutionDTO,
)

logger = logging.getLogger(__name__)


def get_user_query(chat_history: List[PyrisMessage]):
    """
    Extracts the user query from the chat history.
    :param chat_history: List of messages in the chat history.
    :return: The user query as a string.
    """
    if chat_history:
        if chat_history[-1].sender == IrisMessageRole.USER:
            return chat_history[-1].contents[0].text_content
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
                return message.contents[0].text_content
    return "No artifact found in chat history."


def get_chat_history_without_user_query(chat_history: List[PyrisMessage]) -> str:
    """
    Extracts the chat history without the user query.
    :param chat_history: List of messages in the chat history.
    :return: The chat history as a string.
    """
    chat_history_str = "No chat history found."
    if chat_history:
        if chat_history[-1].sender == IrisMessageRole.USER:
            chat_history = chat_history[:-1]
            # remove all TUT_SUG messages because they are not relevant for the prompt
            chat_history = [
                message
                for message in chat_history
                if message.sender != IrisMessageRole.ARTIFACT
            ]
            chat_history_str = "\n".join(
                [
                    f"{message.sender.name}: {message.contents[0].text_content}"
                    for message in chat_history
                ]
            )
    return chat_history_str


def extract_html_from_text(text: str):
    html_pattern = re.compile(
        r"\s*(?P<html>&lt;ul&gt;.*?&lt;/ul&gt;|<ul>.*?</ul>)", re.DOTALL
    )
    match = html_pattern.search(text)

    if match:
        return match.group("html").strip()
    else:
        return None


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
    if dto.exercise is not None:
        return "programming_exercise"
    elif dto.text_exercise is not None:
        return "text_exercise"
    elif dto.lecture_id is not None:
        return "lecture"
    else:
        return "general"


def sort_post_answers(dto):
    """
    Sort the answers of the post by their id
    :param dto: execution data transfer object
    """
    if dto.post is None or dto.post.answers is None:
        return dto
    dto.post.answers.sort(key=lambda x: x.id)
    return dto


def extract_json_from_text(text: str):
    """
    Extracts the JSON string from the given text.
    This function uses a regular expression to find the JSON string
    and then attempts to parse it into a Python dictionary.
    :param text: The input text containing the JSON string.
    :return: A dictionary representation of the JSON string, or None if parsing fails.
    :raises json.JSONDecodeError: If the JSON string cannot be parsed.
    """
    json_pattern = re.compile(r"\{.*?\}", re.DOTALL | re.MULTILINE)
    matches = json_pattern.findall(text)

    if matches:
        json_str = matches[-1]
        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError as e:
            logger.error("JSON decoding failed: %s", e)
            return None
    return None
