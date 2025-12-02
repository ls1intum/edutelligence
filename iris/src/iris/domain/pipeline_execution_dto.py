from pydantic import BaseModel, ConfigDict, Field

from iris.domain.pipeline_execution_settings_dto import (
    PipelineExecutionSettingsDTO,
)
from iris.domain.status.stage_dto import StageDTO


class PipelineExecutionDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    settings: PipelineExecutionSettingsDTO
    initial_stages: list[StageDTO] = Field(default_factory=list, alias="initialStages")
