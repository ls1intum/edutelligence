from fastapi import Depends, Header, HTTPException, Request
from typing import Any
import json
from copy import deepcopy
from pydantic import BaseModel, ValidationError
from module_modeling_llm.core.context import AppContext
from module_modeling_llm.config import Configuration


def get_ctx(request: Request) -> AppContext:
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        # Handles early calls during reload / miswired tests
        raise HTTPException(status_code=503, detail="App context not ready")
    return ctx


def _pydantic_validate_like(model_type: type[BaseModel], data: Any) -> BaseModel:
    # Works for both Pydantic v1 and v2, prioritizing v1 for this project
    if hasattr(model_type, "parse_obj"):  # v1
        return model_type.parse_obj(data)  # type: ignore
    if hasattr(model_type, "model_validate"):  # v2
        return model_type.model_validate(data)  # type: ignore
    raise RuntimeError("Unsupported Pydantic version")


def _deep_merge(a: Any, b: Any) -> Any:
    # Merge b into a (dict/list/scalars). Keeps defaults from a.
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = _deep_merge(a.get(k), v) if k in a else v
        return out
    # For lists/tuples, replace (simpler & predictable); customize if needed
    return deepcopy(b)


async def get_config(
    ctx: AppContext = Depends(get_ctx),
    x_cfg: str | None = Header(None, alias="X-Module-Config"),
) -> Configuration:
    # Always start from startup-wired defaults; never mutate them
    base = ctx.default_config
    config_dict = base.dict() if hasattr(base, "dict") else base.model_dump()  # type: ignore

    if not x_cfg:
        return base.copy(deep=True) if hasattr(base, "copy") else base.model_copy(deep=True)  # type: ignore

    try:
        overrides = json.loads(x_cfg)
        merged = _deep_merge(config_dict, overrides)
        config = _pydantic_validate_like(Configuration, merged)

        # Note: The model configs created from the merged data will need their catalogs
        # set based on their provider. Since we can't set _catalog after creation,
        # we'd need to recreate the model configs with proper factories if they changed.
        # For now, we'll assume the default config catalogs are sufficient.

        return config  # type: ignore
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid X-Module-Config: {exc}")
