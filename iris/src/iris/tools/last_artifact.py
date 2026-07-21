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
    del callback

    def get_last_artifact() -> str:
        """
        Get the last artifact from the chat history.
        Use this before handling any request to regenerate, revise, refine,
        replace, or otherwise change the previous suggestions. The returned
        artifact is the prior version: the new artifact must be nonempty and
        materially different, not a repetition or cosmetic reformatting.
        Returns:
            str: The last artifact content or an error message if not found.
        """
        if chat_history:
            for message in reversed(chat_history):
                if message.sender == IrisMessageRole.ARTIFACT:
                    if message.contents:
                        return message.contents[0].text_content
                    return "Artifact message has no content."
        return "No artifact found in chat history."

    return get_last_artifact
