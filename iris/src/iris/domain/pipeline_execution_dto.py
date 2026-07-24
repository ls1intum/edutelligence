from typing import Optional

from pydantic import BaseModel

from iris.domain.pipeline_execution_settings_dto import (
    PipelineExecutionSettingsDTO,
)


class PipelineExecutionDTO(BaseModel):
    settings: Optional[PipelineExecutionSettingsDTO]

    class Config:
        populate_by_name = True
