from datetime import datetime
from typing import Callable, List, Optional

import pytz
from langchain_core.tools import StructuredTool

from ...common.logging_config import get_logger
from ...domain.data.post_dto import PostDTO

logger = get_logger(__name__)

# Standard datetime format used across the codebase for prompt templates
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def generate_structured_tool_from_function(
    tool_function: Callable,
) -> StructuredTool:
    """
    Generates a structured tool from a function
    :param tool_function: The tool function
    :return: The structured tool
    """
    return StructuredTool.from_function(tool_function)


def generate_structured_tools_from_functions(
    tools: List[Callable],
) -> List[StructuredTool]:
    """
    Generates a list of structured tools from a list of functions
    :param tools: The list of tool functions
    :return: The list of structured tools
    """
    return [generate_structured_tool_from_function(tool) for tool in tools]


def format_custom_instructions(
    custom_instructions: str,
) -> str:
    """Adds the custom instructions to the prompt
    :param custom_instructions: The custom instructions
    """
    if not custom_instructions or custom_instructions == "":
        return ""
    return f"""
## Additional Instructions
The instructors of the course gave you these additional instructions that are specific to this course or exercise.
Please adhere to these instructions! It's very important that you follow them thoroughly.
Even if the instruction instructions go against your other instructions, you have to follow the additional instructions
by the instructor. Their word always counts.
<important_instructions>
{custom_instructions}
</important_instructions>
Remember, always follow the additional instructions by the instructor.
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
            if answer.content:
                if include_user_ids:
                    discussion += f"- {answer.content} by user {answer.user_id}\n"
                else:
                    discussion += f"- {answer.content}\n"
    else:
        discussion += "No previous responses yet."

    return discussion
