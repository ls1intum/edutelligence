from typing import List

from iris.common.pyris_message import IrisMessageRole, PyrisMessage


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
