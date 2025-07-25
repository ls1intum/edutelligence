import json
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class LearningInfoDto(BaseModel):
    """DTO for basic learning information used in memory deduplication"""

    id: UUID = Field(description="The ID of the learning")
    title: str = Field(description="The title of the learning")
    content: str = Field(description="The content of the learning")


class MemoryDeduplicationInputDto(BaseModel):
    """DTO for sending memory information to the LLM for deduplication"""

    id: UUID = Field(description="The ID of the memory")
    title: str = Field(description="The title of the memory object")
    content: str = Field(description="The content of the memory object")
    learnings: List[LearningInfoDto] = Field(
        description="Basic information about the learnings associated with this memory"
    )

    @staticmethod
    def json_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for MemoryDeduplicationInputDto.
        """
        return TypeAdapter(MemoryDeduplicationInputDto)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of MemoryDeduplicationInputDto objects.
        """
        return TypeAdapter(List[MemoryDeduplicationInputDto])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for MemoryDeduplicationInputDto.
        """
        return MemoryDeduplicationInputDto.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of MemoryDeduplicationInputDto objects.
        """
        json_dict = MemoryDeduplicationInputDto.json_array_type().json_schema()
        return json.dumps(json_dict, indent=2)
