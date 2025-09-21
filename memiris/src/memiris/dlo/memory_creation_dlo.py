import json
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class MemoryCreationDLO(BaseModel):
    """
    Data transfer object for memory creation operations.
    Contains the essential fields needed to create a new memory including references to learnings.
    """

    title: str = Field(description="The title of the memory object. Should be short.")
    content: str = Field(
        description="The content of the memory object. "
        "Contains the aggregated information from the learnings connecting them to a cohesive whole."
        "Should include all relevant information from the learnings."
    )
    learnings: List[UUID] = Field(
        description="The list of unique identifiers of learning objects that this memory object was created from."
    )

    @staticmethod
    def json_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for MemoryCreationDLO.
        """
        return TypeAdapter(MemoryCreationDLO)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of MemoryCreationDLO objects.
        """
        return TypeAdapter(List[MemoryCreationDLO])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for MemoryCreationDLO.
        """
        return MemoryCreationDLO.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of MemoryCreationDLO objects.
        """
        memory_json_dict = MemoryCreationDLO.json_array_type().json_schema()

        return json.dumps(memory_json_dict, indent=2)
