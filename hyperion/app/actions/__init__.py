from typing import Dict, Type
import importlib
import inspect
import pkgutil
from pathlib import Path

from app.actions.base_models import ActionHandler

# Registry of action handlers
_action_handlers: Dict[str, Type[ActionHandler]] = {}


def register_action_handler(handler_cls) -> Type[ActionHandler]:
    """Register an action handler class with the system."""
    if not hasattr(handler_cls, "action_name"):
        raise AttributeError("Action handler must have an 'action_name' attribute")

    action_name = handler_cls.action_name
    _action_handlers[action_name] = handler_cls
    return handler_cls


def get_action_handler(action_name: str) -> Type[ActionHandler]:
    """Get an action handler by its action name."""
    handler = _action_handlers.get(action_name)
    if handler is None:
        raise ValueError(f"No handler registered for action '{action_name}'")
    return handler


def autodiscover_handlers():
    """
    Automatically discover and register all action handlers in subdirectories.
    Looks for classes that have an 'action_name' attribute.
    """
    package_dir = Path(__file__).parent
    for _, module_name, is_pkg in pkgutil.iter_modules([str(package_dir)]):
        if is_pkg:
            # Try to import handler.py files specifically
            try:
                handler_module = importlib.import_module(
                    f"app.actions.{module_name}.handler"
                )
                for item_name in dir(handler_module):
                    item = getattr(handler_module, item_name)
                    # Check if it's a class with action_name attribute
                    if inspect.isclass(item) and hasattr(item, "action_name"):
                        register_action_handler(item)
            except ImportError:
                # No handler.py found, that's fine
                pass
