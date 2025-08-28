import os
import configparser
from pathlib import Path
from typing import cast, List, Optional

from pydantic import AnyHttpUrl

from .module.module import Module
from athena.schemas import ExerciseType


class ModuleRegistry:
    """
    Handles the discovery and loading of assessment modules from configuration files
    """

    def __init__(self, config_path: Path):
        self._config_path = config_path
        self._modules: List[Module] = self._load_modules_from_config()

    def _load_modules_from_config(self) -> List[Module]:
        """Reads the .ini file and populates the list of modules"""
        modules_config = configparser.ConfigParser()
        modules_config.read(self._config_path)

        loaded_modules = []
        for section in modules_config.sections():
            module = Module(
                name=section,
                url=cast(
                    AnyHttpUrl,
                    os.environ.get(
                        f"{section.upper()}_URL", modules_config[section]["url"]
                    ),
                ),
                type=ExerciseType(modules_config[section]["type"]),
                supports_evaluation=modules_config[section].getboolean(
                    "supports_evaluation", False
                ),
                supports_non_graded_feedback_requests=modules_config[
                    section
                ].getboolean("supports_non_graded_feedback_requests", False),
                supports_graded_feedback_requests=modules_config[section].getboolean(
                    "supports_graded_feedback_requests", False
                ),
            )
            loaded_modules.append(module)
        return loaded_modules

    def get_all_modules(self) -> List[Module]:
        """Returns a list of all registered modules"""
        return self._modules

    def find_module_by_name(self, name: str) -> Optional[Module]:
        """Finds a module by its unique name"""
        for module in self._modules:
            if module.name == name:
                return module
        return None
