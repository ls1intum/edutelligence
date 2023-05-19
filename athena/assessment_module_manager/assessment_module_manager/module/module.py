from pydantic import BaseModel, Field, AnyHttpUrl

from athena import ExerciseType


class Module(BaseModel):
    """An Athena module, with the URL to the API as well as the type of module."""
    name: str = Field(example="module_example")
    url: AnyHttpUrl = Field(example="http://localhost:5001")
    type: ExerciseType = Field(example=ExerciseType.text)
    secret: str = Field(example="secret")
