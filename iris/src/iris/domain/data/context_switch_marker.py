from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ContextSwitchTransition(str, Enum):
    """The kind of context transition a CTXSWAP marker records."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class ContextSwitchMarker(BaseModel):
    """Typed payload of a CTXSWAP marker message describing a context switch.

    Mirrors the JSON object produced by the Artemis server (``IrisContextSwitchMarker``)
    and embedded in the marker's JSON content. Keep the field aliases and the transition
    values in sync with the server and the Iris client.
    """

    model_config = ConfigDict(populate_by_name=True)

    transition: ContextSwitchTransition
    entity_id: Optional[int] = Field(default=None, alias="entityId")
    name: str = ""
