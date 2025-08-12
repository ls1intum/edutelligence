import json
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class MemoryDeduplicationDLO(BaseModel):
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
        Generate the TypeAdapter for MemoryDeduplicationDLO.
        """
        return TypeAdapter(MemoryDeduplicationDLO)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of MemoryDeduplicationDLO objects.
        """
        return TypeAdapter(List[MemoryDeduplicationDLO])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for MemoryDeduplicationDLO.
        """
        return MemoryDeduplicationDLO.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of MemoryDeduplicationDLO objects.
        """
        learning_json_dict = MemoryDeduplicationDLO.json_array_type().json_schema()

        return json.dumps(learning_json_dict, indent=2)
