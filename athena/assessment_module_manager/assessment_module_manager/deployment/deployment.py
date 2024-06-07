from pydantic import BaseModel, Field, AnyHttpUrl


class Deployment(BaseModel):
    """LMS instance, with the URL and keys."""
    name: str = Field(example="example")
    url: str = Field(example="https://artemis.cit.tum.de")
