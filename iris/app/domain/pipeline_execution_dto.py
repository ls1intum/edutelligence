from pydantic import BaseModel


class PipelineExecutionDTO(BaseModel):
    pass

    class Config:
        populate_by_name = True
