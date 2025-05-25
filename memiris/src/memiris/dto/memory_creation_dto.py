import json
from typing import Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class MemoryCreationDto(BaseModel):
    """
    Data transfer object for memory creation operations.
    Contains the essential fields needed to create a new memory including references to learnings.
    """

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
        Generate the TypeAdapter for MemoryCreationDto.
        """
        return TypeAdapter(MemoryCreationDto)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of MemoryCreationDto objects.
        """
        return TypeAdapter(List[MemoryCreationDto])

    @staticmethod
    def json_schema() -> Dict[str, Dict[str, str]]:
        """
        Generate the JSON schema for MemoryCreationDto.
        """
        return MemoryCreationDto.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of MemoryCreationDto objects.
        """
        memory_json_dict = MemoryCreationDto.json_array_type().json_schema()

        return json.dumps(memory_json_dict, indent=2)
