from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CommandDTO(BaseModel):
    """A generic command Artemis should execute on the client during a running chat pipeline.

    The envelope is intentionally small: ``type`` identifies the command and ``parameters`` carries
    command-specific data. Artemis owns the final validation and execution semantics.
    """

    model_config = ConfigDict(populate_by_name=True)

    type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
