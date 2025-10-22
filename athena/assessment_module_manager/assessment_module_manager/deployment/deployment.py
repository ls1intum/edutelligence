from pydantic import BaseModel, Field


class Deployment(BaseModel):
    """LMS instance, with the URL and name."""
    name: str = Field(examples=["example"])
    url: str = Field(examples=["https://artemis.cit.tum.de"])
