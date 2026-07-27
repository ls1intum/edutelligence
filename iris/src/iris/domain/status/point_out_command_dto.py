from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from iris.domain.status.command_dto import CommandDTO


class PointOutParametersDTO(BaseModel):
    """The parameters of a point-out: which lecture unit, and where in it.

    Used in both directions. Outbound they are what we ask Artemis to navigate to. Inbound they are
    what a COMMAND marker in the chat history recorded about an earlier point-out — the same values,
    plus ``lecture_unit_name``, which only Artemis can resolve and adds when it stores the marker.
    """

    model_config = ConfigDict(populate_by_name=True)

    lecture_unit_id: int = Field(alias="lectureUnitId", gt=0)
    page: Optional[int] = Field(default=None, ge=1)  # PDF pages start at 1
    timestamp: Optional[float] = Field(default=None, ge=0)  # video time in seconds
    lecture_unit_name: Optional[str] = Field(default=None, alias="lectureUnitName")

    @model_validator(mode="after")
    def require_position(self):
        if self.page is None and self.timestamp is None:
            raise ValueError("Point-out command must include a page or a timestamp")
        return self

    def describe_position(self) -> str:
        """Describe the pointed-to position the way the LLM should read it back.

        The page is named as the *index* page — it is the point-out id, not the number printed on
        the slide — so the agent can tell the two apart and never quotes this one to the student.
        """
        targets = []
        if self.page is not None:
            targets.append(f"index page {self.page}")
        if self.timestamp is not None:
            targets.append(f"the video at {round(self.timestamp)}s")
        unit = (
            f"lecture unit '{self.lecture_unit_name}' (id {self.lecture_unit_id})"
            if self.lecture_unit_name
            else f"lecture unit {self.lecture_unit_id}"
        )
        position = " and ".join(targets)
        return f"{position} of {unit}"


class PointOutCommandDTO(CommandDTO):
    """A command telling Artemis to point the student to a specific position in the lecture
    combined view they are currently looking at.

    Produced by the combined-view point-out tool and sent synchronously to Artemis mid-pipeline.
    Artemis navigates the client if the combined view is still open and replies whether it was
    carried out (see ``CommandResultDTO``). The ``type`` discriminator selects the command variant
    on the Artemis side; ``parameters`` narrows the generic ``CommandDTO`` payload to the
    point-out shape, so an invalid position fails here rather than silently on the Artemis side.
    """

    type: str = "pointOut"
    parameters: PointOutParametersDTO

    def __init__(
        self,
        lecture_unit_id: int,
        page: Optional[int] = None,
        timestamp: Optional[float] = None,
    ):
        super().__init__(
            type="pointOut",
            parameters=PointOutParametersDTO(
                lecture_unit_id=lecture_unit_id, page=page, timestamp=timestamp
            ),
        )
