from typing import Optional

from pydantic import BaseModel


class CommandResultDTO(BaseModel):
    """The result Artemis returns for a command executed mid-pipeline: whether it was actually
    carried out on the client, with an optional short reason when it was not."""

    applied: bool
    reason: Optional[str] = None
