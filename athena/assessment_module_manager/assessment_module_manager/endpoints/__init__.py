"""
All available endpoints for the assessment module manager.
"""

from .modules_proxy_endpoint import proxy_to_module, router as proxy_router
from .health_endpoint import get_health, router as health_router
from .modules_endpoint import get_modules, router as modules_router

__all__ = [
    "get_health",
    "get_modules",
    "proxy_to_module",
]

routers = [health_router, modules_router, proxy_router]
