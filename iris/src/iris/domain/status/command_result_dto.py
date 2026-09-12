from pydantic import BaseModel


class CommandResultDTO(BaseModel):
    """The result Artemis returns for a command executed mid-pipeline: whether it was actually
    carried out on the client (e.g. the combined view was still open and it navigated).
    """

    applied: bool
