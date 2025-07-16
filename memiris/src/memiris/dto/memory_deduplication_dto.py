import json
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class MemoryDeduplicationDto(BaseModel):
    """
    Data transfer object for memory deduplication operations.
    Represents a memory that results from deduplicating multiple memories.
    """

    title: str = Field(description="The title of the memory object. Should be short.")
    content: str = Field(
        description="The content of the memory object. "
        "Contains the aggregated information from the learnings connecting them to a cohesive whole."
    )
    memories: List[UUID] = Field(
        description="The list of duplicated memories this memory was deduplicated from."
    )

    @staticmethod
    def json_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for MemoryDeduplicationDto.
        """
        return TypeAdapter(MemoryDeduplicationDto)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of MemoryDeduplicationDto objects.
        """
        return TypeAdapter(List[MemoryDeduplicationDto])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for MemoryDeduplicationDto.
        """
        return MemoryDeduplicationDto.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of MemoryDeduplicationDto objects.
        """
        learning_json_dict = MemoryDeduplicationDto.json_array_type().json_schema()

        return json.dumps(learning_json_dict, indent=2)
