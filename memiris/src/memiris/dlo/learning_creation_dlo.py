import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field, TypeAdapter


class LearningCreationDLO(BaseModel):
    """
    Data transfer object for learning creation operations.
    Contains the essential fields needed to create a new learning entry.
    """

    title: str = Field(description="The title of the learning object. Should be short.")
    content: str = Field(
        description="The content of the learning object. "
        "Contains the information that was learned and details about it."
    )

    @staticmethod
    def json_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for LearningCreationDLO.
        """
        return TypeAdapter(LearningCreationDLO)

    @staticmethod
    def json_array_type() -> TypeAdapter:
        """
        Generate the TypeAdapter for an array of LearningCreationDLO objects.
        """
        return TypeAdapter(List[LearningCreationDLO])

    @staticmethod
    def json_schema() -> Dict[str, Any]:
        """
        Generate the JSON schema for LearningCreationDLO.
        """
        return LearningCreationDLO.json_type().json_schema()

    @staticmethod
    def json_array_schema() -> str:
        """
        Generate the JSON schema for an array of LearningCreationDLO objects.
        """
        learning_json_dict = LearningCreationDLO.json_array_type().json_schema()

        return json.dumps(learning_json_dict, indent=2)
