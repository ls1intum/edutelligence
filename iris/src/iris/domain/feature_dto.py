from pydantic import BaseModel


class FeatureDTO(BaseModel):
    id: str
    name: str
    description: str
