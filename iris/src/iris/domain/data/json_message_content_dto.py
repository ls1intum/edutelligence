import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JsonMessageContentDTO(BaseModel):
    """A polymorphic Artemis message content carrying a raw JSON value."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    type: Literal["json"] = "json"
    json_content: Any = Field(alias="jsonContent")

    @field_validator("json_content", mode="before")
    @classmethod
    def parse_legacy_json_string(cls, value: Any) -> Any:
        """Accept old Iris callers while serializing the Artemis raw-JSON wire shape."""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError("jsonContent must contain valid JSON") from error
        return value
