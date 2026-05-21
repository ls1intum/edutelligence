"""
All available endpoints for the assessment module manager.
"""
from .modules_proxy_endpoint import proxy_to_module
from .health_endpoint import get_health
from .modules_endpoint import get_modules
from .evaluate_endpoint import evaluate_submission

__all__ = [
    "evaluate_submission",
    "get_health",
    "get_modules",
    "proxy_to_module",
]
