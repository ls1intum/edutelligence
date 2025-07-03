from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import Any

_SUBMODULES = {
    "llm_config_loader",
    "llm_capabilities_loader",
    "model_loaders",
}


def __getattr__(name: str) -> Any:
    if name in _SUBMODULES:
        module: ModuleType = importlib.import_module(f"{__name__}.{name}")
        setattr(sys.modules[__name__], name, module)
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SUBMODULES)


__all__ = list(_SUBMODULES)
