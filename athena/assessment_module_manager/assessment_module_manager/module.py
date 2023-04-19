from typing import List
import configparser

from athena import ExerciseType
from pydantic import BaseModel, Field, AnyHttpUrl

from .app import app


class Module(BaseModel):
    """An Athena module, with the URL to the API as well as the type of module."""
    name: str = Field(example="module_example")
    url: AnyHttpUrl = Field(example="http://localhost:5001")
    type: ExerciseType = Field(example=ExerciseType.text)


@app.get("/modules")
def get_module_list() -> List[Module]:
    """Get a list of all Athena modules that are available."""
    modules = configparser.ConfigParser()
    modules.read("modules.ini")
    return [
        Module(name=module, url=modules[module]["url"], type=modules[module]["type"])
        for module in modules.sections()
    ]
