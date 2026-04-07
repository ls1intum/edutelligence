from typing import Callable, List

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.web.status.status_update import StatusCallback


def create_tool_get_last_artifact(
    chat_history: List[PyrisMessage], callback: StatusCallback
) -> Callable[[], str]:
    """
    Create a tool that retrieves the last artifact from the chat history.
    Args:
        chat_history (List[PyrisMessage]): List of messages in the chat history.
        callback (StatusCallback): Callback for status updates.
    Returns:
        Callable[[], str]: Function that returns the last artifact content.
    """

    def get_last_artifact() -> str:
        """
        Get the last artifact from the chat history.
        Use this if you want to refer to the last artifact in the conversation.
        Returns:
            str: The last artifact content or an error message if not found.
        """
        callback.in_progress("Retrieving last artifact ...")
        if chat_history:
            for message in reversed(chat_history):
                if message.sender == IrisMessageRole.ARTIFACT:
                    if message.contents:
                        return message.contents[0].text_content
                    return "Artifact message has no content."
        return "No artifact found in chat history."

    return get_last_artifact
