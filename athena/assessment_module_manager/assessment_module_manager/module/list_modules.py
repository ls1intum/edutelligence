import configparser
from typing import List, cast
from pathlib import Path

from pydantic import AnyHttpUrl

from athena import ExerciseType

from .module import Module


def list_modules() -> List[Module]:
    """Get a list of all Athena modules that are available."""
    modules_config = configparser.ConfigParser()
    modules_config.read(Path(__file__).parent.parent.parent / "modules.ini")
    return [
        Module(
            name=module,
            url=cast(AnyHttpUrl, modules_config[module]["url"]),
            type=ExerciseType(modules_config[module]["type"]),
            supports_evaluation=modules_config[module].getboolean("supports_evaluation"),
        )
        for module in modules_config.sections()
    ]
