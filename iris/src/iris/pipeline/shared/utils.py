from datetime import datetime
from typing import Callable, List, Optional

from langchain_core.tools import StructuredTool

from ...common.logging_config import get_logger

logger = get_logger(__name__)


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
        return dt.strftime("%Y-%m-%d %H:%M:%S")
