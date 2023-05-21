import configparser
from dataclasses import dataclass

from .schemas.exercise_type import ExerciseType


@dataclass
class ModuleConfig:
    """Config from module.conf."""
    name: str
    type: ExerciseType
    port: int


def get_module_config() -> ModuleConfig:
    """Get the module from the config file."""
    config = configparser.ConfigParser()
    config.read("module.conf")
    return ModuleConfig(
        name=config["module"]["name"],
        type=ExerciseType(config["module"]["type"]),
        port=int(config["module"]["port"]),
    )
