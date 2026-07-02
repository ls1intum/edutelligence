from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field


class EpisodeHintDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    level: Literal["ambient", "active"]
    text: str
    at_session_s: float = Field(alias="atSessionS")


class EpisodeDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    episode_id: str = Field(alias="episodeId")
    is_new: bool = Field(alias="isNew")
    hints: List[EpisodeHintDTO] = Field(default_factory=list)
