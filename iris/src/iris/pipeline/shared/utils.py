from typing import Callable, List, Tuple

from langchain_core.tools import StructuredTool

from ...domain import FeatureDTO
from ...llm.external.model import LanguageModel


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
) -> List[FeatureDTO]:
    """
    Filters variants based on available language models.

    :param available_llms: List of available language models
    :param variant_specs: List of tuples, each containing:
        - List of model strings: ALL models in this list must be available for the variant to be enabled
        - FeatureDTO for the variant

    :return: List of FeatureDTO objects for supported variants
    """
    available_models = [llm.model for llm in available_llms]
    supported_variants = []

    for required_models, feature_dto in variant_specs:
        # Check if ALL required models are available
        if all(
            any(required_model in model for model in available_models)
            for required_model in required_models
        ):
            supported_variants.append(feature_dto)

    return supported_variants
