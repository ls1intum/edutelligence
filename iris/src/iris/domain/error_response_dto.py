from pydantic import BaseModel, Field


class IrisErrorResponseDTO(BaseModel):
    error_message: str = Field(alias="errorMessage")
