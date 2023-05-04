from .modules_proxy_endpoint import proxy_to_module
from .health_endpoint import get_health
from .modules_endpoint import get_modules

endpoints = [
    "get_health",
    "get_modules",
    "proxy_to_module",
]
__all__ = ["endpoints"]
