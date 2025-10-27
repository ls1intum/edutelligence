import configparser
from dataclasses import dataclass
import json
from pydantic import BaseModel, ValidationError
from typing import TypeVar, Optional, Type

from fastapi import HTTPException, Header, status

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


C = TypeVar("C", bound=BaseModel)
def get_dynamic_module_config_factory(module_config_type: Optional[Type[C]]):
    """Create a function that gets the dynamic module config from the request header."""

    async def get_dynamic_module_config(module_config: Optional[str] = Header(None, alias="X-Module-Config")) -> Optional[C]:
        """Get the dynamic module config from the request header."""
        if module_config_type is None:
            return None

        if module_config is not None:
            try:
                config_dict = json.loads(module_config)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, 
                                    detail="Invalid module config received, could not parse JSON from X-Module-Config header.") from exc
            
            try:
                return module_config_type.model_validate(config_dict)
            except ValidationError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, 
                                    detail=f"Validation error for module config: {exc}") from exc
        
        # Return a default instance of module_config_type when module_config is None
        return module_config_type()
    
    return get_dynamic_module_config
