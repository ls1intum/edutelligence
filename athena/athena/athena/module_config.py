import configparser
from dataclasses import dataclass
import json
from pydantic import BaseModel, ValidationError
from typing import TypeVar, Optional, Type
from fastapi import HTTPException, Header, Request, status

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


def get_header_module_config_factory(module_config_type: Type[C]):
    """Parse X-Module-Config into the concrete model, or return None."""

    async def dep(
        module_config: Optional[str] = Header(None, alias="X-Module-Config")
    ) -> Optional[C]:
        if module_config is None:
            return None
        try:
            data = json.loads(module_config)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid module config: could not parse JSON from X-Module-Config.",
            ) from exc
        try:
            return module_config_type.model_validate(data)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Validation error for module config: {exc}",
            ) from exc

    return dep


def get_default_module_config_from_app_factory(module_config_type: Type[C]):
    """Fetch default from request.app.state.module_config (no DI container)."""

    async def dep(request: Request) -> C:
        cfg = getattr(getattr(request, "app", None).state, "module_config", None)  # type: ignore
        if cfg:
            return cfg
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "No module config available. Provide X-Module-Config header or attach "
                "`module_config` to app.state."
            ),
        )

    return dep


def get_dynamic_module_config_factory(module_config_type: Type[C]):
    """Prefer header override; otherwise default from app.state.module_config."""
    from fastapi import Depends

    HeaderDep = get_header_module_config_factory(module_config_type)
    DefaultDep = get_default_module_config_from_app_factory(module_config_type)

    async def dep(
        header_cfg: Optional[C] = Depends(HeaderDep),  # type: ignore
        default_cfg: C = Depends(DefaultDep),  # type: ignore
    ) -> C:
        return header_cfg or default_cfg

    return dep
