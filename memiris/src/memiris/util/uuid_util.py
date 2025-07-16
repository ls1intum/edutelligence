from typing import Optional
from uuid import UUID


def is_valid_uuid(uuid_string: str) -> bool:
    """
    Check if a string is a valid UUID v4.

    Args:
        uuid_string (str): The string to check.

    Returns:
        bool: True if the string is a valid UUID, False otherwise.
    """
    try:
        UUID(uuid_string, version=4)
        return True
    except ValueError:
        return False


def to_uuid(uuid_string: str) -> Optional[UUID]:
    """
    Convert a string to a UUID object.

    Args:
        uuid_string (str): The string to convert.

    Returns:
        UUID: The UUID object.
    """
    if not is_valid_uuid(uuid_string):
        return None
    return UUID(uuid_string, version=4)
