import json
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class MemoryDLO(BaseModel):
    """
    Data transfer object for representing a memory.
    Contains the complete representation of a memory object including its identifier and learning references.
    """

    id: UUID = Field(description="The unique identifier of the memory object.")
    title: str = Field(description="The title of the memory object. Should be short.")
    content: str = Field(
        description="The content of the memory object. "
        "Contains the aggregated information from the learnings connecting them to a cohesive whole."
    )
    learnings: List[UUID] = Field(
        description="The list of unique identifiers of learning objects that this memory object was created from."
    )

    @staticmethod
    def json_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for MemoryDLO.
        """
        return TypeAdapter(MemoryDLO)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of MemoryDLO objects.
        """
        return TypeAdapter(List[MemoryDLO])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for MemoryDLO.
        """
        return MemoryDLO.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of MemoryDLO objects.
        """
        memory_json_dict = MemoryDLO.json_array_type().json_schema()

        return json.dumps(memory_json_dict, indent=2)
