from datetime import datetime
from typing import Optional

import pytz

from ...common.logging_config import get_logger
from ...domain.data.post_dto import PostDTO

logger = get_logger(__name__)

# Standard datetime format used across the codebase for prompt templates
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

REDACTED_ANSWER_PLACEHOLDER = "[message hidden - user opted out of AI]"


def format_custom_instructions(
    custom_instructions: str,
) -> str:
    """Render the instructors' own instructions for the end of a system prompt.

    They come last so they take precedence over the general guidance above.
    :param custom_instructions: The custom instructions
    """
    if not custom_instructions or custom_instructions == "":
        return ""
    return f"""
# Instructions from the course instructors
The instructors of this course added the following instructions for this course or exercise.
Follow them closely. If they conflict with the general guidance above, the instructors'
instructions take precedence.
<instructor_instructions>
{custom_instructions}
</instructor_instructions>
"""


def get_current_utc_datetime_string() -> str:
    """
    Get the current UTC datetime as a formatted string.

    Returns:
        Formatted datetime string 'YYYY-MM-DD HH:MM:SS' in UTC.
    """
    return datetime.now(tz=pytz.UTC).strftime(DATETIME_FORMAT)


def datetime_to_string(dt: Optional[datetime]) -> str:
    """
    Convert a datetime to a formatted string.

    Args:
        dt: The datetime to convert.

    Returns:
        Formatted datetime string 'YYYY-MM-DD HH:MM:SS' or 'No date provided'.
    """
    if dt is None:
        return "No date provided"
    else:
        return dt.strftime(DATETIME_FORMAT)


def format_post_discussion(post: PostDTO, include_user_ids: bool = False) -> str:
    """
    Format a post and its answers into a readable discussion string.
    Use this if you want to provide additional context regarding the discussion of a post.

    Args:
        post: The post DTO containing the question and answers.
        include_user_ids: Whether to include user IDs in the output.

    Returns:
        Formatted discussion string.
    """
    if not post or not post.content:
        return "No post content available."

    if include_user_ids:
        discussion = f"The post's question is: {post.content} by user {post.user_id}\n"
    else:
        discussion = f"Student's question: {post.content}\n"

    if post.answers:
        discussion += "Previous responses:\n"
        for answer in post.answers:
            if answer.redacted:
                text = REDACTED_ANSWER_PLACEHOLDER
            else:
                text = answer.content or ""
            if text:
                if include_user_ids:
                    discussion += f"- {text} by user {answer.user_id}\n"
                else:
                    discussion += f"- {text}\n"
    else:
        discussion += "No previous responses yet."

    return discussion
