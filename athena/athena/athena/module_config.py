import configparser
from dataclasses import dataclass
import json
from pydantic import BaseModel, ValidationError
from typing import TypeVar, Optional, Type

from fastapi import HTTPException, Header, status

from .schemas.exercise_type import ExerciseType

_MODULE_CONFIG_FROM_HEADER_ATTR = "_athena_module_config_from_header"


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


def _mark_module_config_source(module_config: Optional[C], from_header: bool) -> Optional[C]:
    """Annotate dynamic module configs so callers can distinguish defaults from explicit overrides."""
    if module_config is None:
        return None

    object.__setattr__(module_config, _MODULE_CONFIG_FROM_HEADER_ATTR, from_header)
    return module_config


def is_explicit_module_config(module_config: Optional[BaseModel]) -> bool:
    """Return whether the module config was explicitly provided via X-Module-Config."""
    if module_config is None:
        return False

    return bool(getattr(module_config, _MODULE_CONFIG_FROM_HEADER_ATTR, False))


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
                return _mark_module_config_source(module_config_type.model_validate(config_dict), from_header=True)
            except ValidationError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, 
                                    detail=f"Validation error for module config: {exc}") from exc
        
        # Return a default instance of module_config_type when module_config is None
        return _mark_module_config_source(module_config_type(), from_header=False)
    
    return get_dynamic_module_config
