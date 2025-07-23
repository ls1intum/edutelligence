import json
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class LearningDto(BaseModel):
    """
    Data transfer object for representing a learning.
    Contains the complete representation of a learning object including its identifier.
    """

    id: UUID = Field(description="The unique identifier of the learning object.")
    title: str = Field(description="The title of the learning object. Should be short.")
    content: str = Field(
        description="The content of the learning object. "
        "Contains the information that was learned and details about it."
    )

    @staticmethod
    def json_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for LearningDto.
        """
        return TypeAdapter(LearningDto)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of LearningDto objects.
        """
        return TypeAdapter(List[LearningDto])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for LearningDto.
        """
        return LearningDto.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of LearningDto objects.
        """
        learning_json_dict = LearningDto.json_array_type().json_schema()

        return json.dumps(learning_json_dict, indent=2)
