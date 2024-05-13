from pydantic import BaseModel, Field, AnyHttpUrl


class Deployment(BaseModel):
    """An Artemis instance, with the URL and keys."""
    name: str = Field(example="example")
    url: AnyHttpUrl = Field(example="https://artemis.cit.tum.de")
    artemis_id: str = Field(example="artemis_example")
