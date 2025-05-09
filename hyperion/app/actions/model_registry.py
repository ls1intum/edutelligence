"""
Dynamic registry for action input and update models.

This module enables automatic discovery and registration of action models,
creating Union types dynamically as new actions are registered.
"""

from typing import Dict, List, Type, Union, TypeVar, get_args, get_origin
import importlib
import inspect
from pydantic import create_model

from app.actions.base_models import ActionInput, ActionUpdate, ProgressUpdate, ResultUpdate

# Type registries
_input_models: Dict[str, Type[ActionInput]] = {}
_update_models: Dict[str, List[Type[ActionUpdate]]] = {}

# Dynamic union types that will be updated as models are registered
InputUnion = Union[ActionInput]  # Default with just the base type
UpdateUnion = Union[ActionUpdate]  # Default with just the base type

def register_input_model(model_cls: Type[ActionInput]) -> None:
    """Register an input model for an action."""
    action_name = None
    # Check if the model has a default value for action
    for field_name, field in model_cls.model_fields.items():
        if field_name == "action" and field.default is not None:
            action_name = field.default
    
    if not action_name:
        raise ValueError(f"Input model {model_cls.__name__} must have a default value for 'action' field")
    
    _input_models[action_name] = model_cls
    _update_dynamic_unions()

def register_update_model(model_cls: Type[ActionUpdate]) -> None:
    """Register an update model for an action."""
    # Determine the action this update belongs to based on naming convention
    # For example: ConsistencyCheckProgressUpdate -> consistency_check
    class_name = model_cls.__name__
    
    # Try to extract action name from class name
    action_name = None
    for input_action_name, input_model in _input_models.items():
        # Convert action_name from snake_case to camel case for comparison
        camel_action = ''.join(word.capitalize() for word in input_action_name.split('_'))
        if camel_action in class_name:
            action_name = input_action_name
            break
    
    if not action_name:
        raise ValueError(f"Could not determine action for update model {class_name}")
    
    if action_name not in _update_models:
        _update_models[action_name] = []
    
    _update_models[action_name].append(model_cls)
    _update_dynamic_unions()

def _update_dynamic_unions():
    """Update the dynamic union types based on registered models."""
    global InputUnion, UpdateUnion
    
    if _input_models:
        # Create a new Union type with all registered input models
        InputUnion = Union[tuple(_input_models.values())]
    
    # Flatten the update models list
    all_update_models = []
    for models in _update_models.values():
        all_update_models.extend(models)
    
    if all_update_models:
        # Create a new Union type with all registered update models
        UpdateUnion = Union[tuple(all_update_models)]

def get_input_model(action_name: str) -> Type[ActionInput]:
    """Get the input model for a specific action."""
    model = _input_models.get(action_name)
    if model is None:
        raise ValueError(f"No input model registered for action '{action_name}'")
    return model

def get_update_models(action_name: str) -> List[Type[ActionUpdate]]:
    """Get all update models for a specific action."""
    models = _update_models.get(action_name, [])
    if not models:
        raise ValueError(f"No update models registered for action '{action_name}'")
    return models

def get_input_union() -> type:
    """Get the current Union type for all registered input models."""
    return InputUnion

def get_update_union() -> type:
    """Get the current Union type for all registered update models."""
    return UpdateUnion

def autodiscover_models():
    """
    Automatically discover and register all action models in subdirectories.
    Looks for:
    - Classes that inherit from ActionInput
    - Classes that inherit from ProgressUpdate or ResultUpdate
    """
    import os
    from pathlib import Path
    import pkgutil
    
    # Get the directory of the current file (model_registry.py) and use its parent directory
    package_dir = Path(__file__).parent
    
    for _, module_name, is_pkg in pkgutil.iter_modules([str(package_dir)]):
        if is_pkg and module_name != "__pycache__":
            # Try to import models.py files from action subdirectories
            try:
                models_module = importlib.import_module(f"app.actions.{module_name}.models")
                for item_name in dir(models_module):
                    item = getattr(models_module, item_name)
                    # Check if it's a class that inherits from our base models
                    if inspect.isclass(item):
                        if issubclass(item, ActionInput) and item != ActionInput:
                            register_input_model(item)
                        elif issubclass(item, ProgressUpdate) and item != ProgressUpdate:
                            register_update_model(item)
                        elif issubclass(item, ResultUpdate) and item != ResultUpdate:
                            register_update_model(item)
            except ImportError:
                # No models.py found, that's fine
                pass