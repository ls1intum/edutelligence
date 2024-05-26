from typing import List, Optional

from pydantic import BaseModel, Field

from app.domain.pipeline_execution_settings_dto import PipelineExecutionSettingsDTO
from app.domain.status.stage_dto import StageDTO


class PipelineExecutionDTO(BaseModel):
    settings: PipelineExecutionSettingsDTO
    initial_stages: Optional[List[StageDTO]] = Field(
        default=None, alias="initialStages"
    )

    class Config:
        populate_by_name = True
