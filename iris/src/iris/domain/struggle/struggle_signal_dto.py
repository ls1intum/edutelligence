from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field

BoundaryType = Literal["FM", "FM_PLUS", "E4", "N1", "STATE"]
ComponentName = Literal[
    "feedbackViewing", "regionPersistence", "errorDistance", "typing", "gap", "n4"
]


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class StruggleAlert(_CamelModel):
    t_session_s: float = Field(alias="tSessionS")
    primary_boundary: BoundaryType = Field(alias="primaryBoundary")
    boundary_types: List[BoundaryType] = Field(alias="boundaryTypes")
    severity: float
    path: Literal["armed", "e6"]
    in_warmup: bool = Field(alias="inWarmup")
    in_grace: bool = Field(alias="inGrace")


class StruggleTick(_CamelModel):
    t: float
    s: float
    v: float


class StruggleComponent(_CamelModel):
    name: ComponentName
    value: float


class StruggleSignal(_CamelModel):
    alert: StruggleAlert
    trajectory: List[StruggleTick]
    dominant_components: List[StruggleComponent] = Field(alias="dominantComponents")
    session_seconds: float = Field(alias="sessionSeconds")
