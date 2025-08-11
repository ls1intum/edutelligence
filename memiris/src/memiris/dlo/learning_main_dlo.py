import json
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter


class LearningDLO(BaseModel):
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
        Generate the TypeAdapter for LearningDLO.
        """
        return TypeAdapter(LearningDLO)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of LearningDLO objects.
        """
        return TypeAdapter(List[LearningDLO])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for LearningDLO.
        """
        return LearningDLO.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of LearningDLO objects.
        """
        learning_json_dict = LearningDLO.json_array_type().json_schema()

        return json.dumps(learning_json_dict, indent=2)
