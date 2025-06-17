from typing import Callable, Dict, Any

APPROACH_IMPLEMENTATIONS: Dict[str, Callable[..., Any]] = {}

def register_approach(name: str) -> Callable:
    """
    A decorator that registers an approach implementation function in our registry.
    
    Usage:
        @register_approach("basic")
        async def generate_suggestions(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        if name in APPROACH_IMPLEMENTATIONS:
            raise ValueError(f"Approach with name '{name}' is already registered.")
        APPROACH_IMPLEMENTATIONS[name] = func
        return func
    return decorator
