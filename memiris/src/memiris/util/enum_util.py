from enum import Enum
from typing import Any, Dict, Type


def get_enum_values_with_descriptions(
    enum_class: Type[Enum],
) -> Dict[str, Dict[str, Any]]:
    """
    Extract enum values with their descriptions from docstrings.

    This function parses the enum class docstring to find descriptions for each enum value.
    The format expected in the docstring is:

    ENUM_VALUE: Description of the enum value

    Args:
        enum_class: The Enum class to extract values and descriptions from

    Returns:
        A dictionary mapping enum names to a dictionary containing 'value' and 'description'
    """
    result = {}

    # Get the class docstring
    docstring = enum_class.__doc__ or ""

    # Parse the docstring to find descriptions
    descriptions = {}
    for line in docstring.split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue

        parts = line.split(":", 1)
        if len(parts) == 2:
            enum_name = parts[0].strip()
            description = parts[1].strip()
            descriptions[enum_name] = description

    # Create the result dictionary
    for member in enum_class:
        name = member.name
        value = member.value
        description = descriptions.get(name, name.replace("_", " ").title())

        result[name.lower()] = {"value": value, "description": description}

    return result
