from typing import Optional

from pydantic import BaseModel, Field

from iris.domain.pipeline_execution_settings_dto import (
    PipelineExecutionSettingsDTO,
)
from iris.domain.status.stage_dto import StageDTO


class PipelineExecutionDTO(BaseModel):
    settings: Optional[PipelineExecutionSettingsDTO]
    initial_stages: Optional[list[StageDTO]] = Field(
        default=None, alias="initialStages"
    )

    class Config:
        populate_by_name = True
