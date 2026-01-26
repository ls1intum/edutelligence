from datetime import datetime
from typing import Callable, List, Optional, Tuple

from langchain_core.tools import StructuredTool

from ...common.logging_config import get_logger
from ...domain import FeatureDTO
from ...llm.external.model import LanguageModel

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


def filter_variants_by_available_models(
    available_llms: List[LanguageModel],
    variant_specs: List[Tuple[List[str], FeatureDTO]],
    pipeline_name: str = "Unknown",
) -> List[FeatureDTO]:
    """
    Filters variants based on available language models.

    :param available_llms: List of available language models
    :param variant_specs: List of tuples, each containing:
        - List of model strings: ALL models in this list must be available for the variant to be enabled
        - FeatureDTO for the variant
    :param pipeline_name: The name of the pipeline for logging purposes

    :return: List of FeatureDTO objects for supported variants
    """
    available_models = [llm.model for llm in available_llms]
    supported_variants = []

    for required_models, feature_dto in variant_specs:
        # Check if ALL required models are available
        missing_models = []
        for required_model in required_models:
            if not any(required_model in model for model in available_models):
                missing_models.append(required_model)

        if not missing_models:
            supported_variants.append(feature_dto)
        else:
            # Log a warning for unavailable variants
            logger.warning(
                "⚠️ VARIANT UNAVAILABLE: '%s' variant (id: %s) for '%s' "
                "cannot be used because the following required model(s) are missing: %s. "
                "To enable this variant, add these models to your LLM configuration.",
                feature_dto.name,
                feature_dto.id,
                pipeline_name,
                ", ".join(missing_models),
            )

    return supported_variants


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
