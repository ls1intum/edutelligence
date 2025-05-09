"""
Dynamic registry for action input and update models.

This module enables automatic discovery and registration of action models,
creating Union types dynamically as new actions are registered.
"""

from typing import Dict, List, Type, Union, Any, Optional, Annotated, Callable
import importlib
import inspect
from pydantic import Field, Tag

from app.actions.base_models import ActionInput, ActionUpdate

# Type registries
_input_models: Dict[str, Type[ActionInput]] = {}
_update_models: Dict[str, Dict[str, List[Type[ActionUpdate]]]] = {}

# Start with base types as defaults
InputUnion = Union[ActionInput]
# For update models, we'll create per-action unions for nested discrimination
ActionUpdateUnions = {}

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
    # Initialize update models dict for this action
    if action_name not in _update_models:
        _update_models[action_name] = {}
        
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
    
    # Get update type from model
    update_type = None
    for field_name, field in model_cls.model_fields.items():
        if field_name == "update_type" and field.default is not None:
            update_type = field.default
    
    if not update_type:
        raise ValueError(f"Update model {model_cls.__name__} must have a default value for 'update_type' field")
    
    # Extract the update category (e.g., 'progress', 'result') from the update type
    # For example: 'consistency_check_progress' -> 'progress'
    update_category = update_type.split('_')[-1] if '_' in update_type else update_type
    
    # Initialize dictionaries if needed
    if action_name not in _update_models:
        _update_models[action_name] = {}
    
    if update_category not in _update_models[action_name]:
        _update_models[action_name][update_category] = []
    
    _update_models[action_name][update_category].append(model_cls)
    _update_dynamic_unions()

def _update_dynamic_unions():
    """Update the dynamic union types based on registered models."""
    global InputUnion, ActionUpdateUnions
    
    if _input_models:
        # Create a new Union type with all registered input models
        InputUnion = Union[tuple(_input_models.values())]
    
    # Create per-action unions for update models
    # This allows for better nested discrimination in the schema
    ActionUpdateUnions = {}
    for action_name, categories in _update_models.items():
        # Create per-category unions
        category_unions = {}
        for category, models in categories.items():
            if models:
                category_unions[category] = Annotated[
                    Union[tuple(models)],
                    Field(discriminator="update_type"),
                    Tag(category)
                ]
        
        # Create union of all update models for this action
        if category_unions:
            all_models = []
            for models in categories.values():
                all_models.extend(models)
                
            if all_models:
                # Create a union for all models of this action
                ActionUpdateUnions[action_name] = Annotated[
                    Union[tuple(all_models)],
                    Field(discriminator="update_type"),
                    Tag(action_name)
                ]

def get_input_model(action_name: str) -> Type[ActionInput]:
    """Get the input model for a specific action."""
    model = _input_models.get(action_name)
    if model is None:
        raise ValueError(f"No input model registered for action '{action_name}'")
    return model

def get_update_models(action_name: str) -> List[Type[ActionUpdate]]:
    """Get all update models for a specific action."""
    models = []
    if action_name in _update_models:
        for category_models in _update_models[action_name].values():
            models.extend(category_models)
    
    if not models:
        raise ValueError(f"No update models registered for action '{action_name}'")
    return models

def get_input_union() -> type:
    """Get the current Union type for all registered input models."""
    # Use Annotated to apply a better title for the OpenAPI schema
    return Annotated[InputUnion, Field(discriminator="action", title="ActionInput")]

def get_update_union() -> type:
    """
    Get a nested discriminated union of all action update models.
    This creates a cleaner schema with action-specific updates grouped together.
    """
    if not ActionUpdateUnions:
        # Return a simple union if we don't have any registered models
        return Annotated[Union[ActionUpdate], Field(discriminator="update_type", title="ActionUpdate")]
    
    # Create a nested discriminated union by action name
    action_values = tuple(ActionUpdateUnions.values())
    return Annotated[
        Union[action_values],
        Field(discriminator="action_name", title="ActionUpdate"),
        Tag("action_updates")
    ]

def update_type_discriminator(obj: Any) -> Optional[str]:
    """
    A callable discriminator function for update types.
    Returns the update type from the object, or None if not found.
    """
    if isinstance(obj, dict) and "update_type" in obj:
        return obj["update_type"]
    elif hasattr(obj, "update_type"):
        return obj.update_type
    return None

def action_name_discriminator(obj: Any) -> Optional[str]:
    """
    A callable discriminator function for action names.
    Extracts the action name from the update type, or None if not found.
    """
    update_type = update_type_discriminator(obj)
    if update_type:
        # Extract action name from update type (e.g., consistency_check_progress -> consistency_check)
        parts = update_type.split('_')
        if len(parts) >= 2:
            # Find how many parts make up the action name by looking at registered actions
            for i in range(len(parts) - 1, 0, -1):
                potential_action = "_".join(parts[:i])
                if potential_action in _input_models:
                    return potential_action
    return None

def autodiscover_models():
    """
    Automatically discover and register all action models in subdirectories.
    Looks for:
    - Classes that inherit from ActionInput
    - Classes that inherit from ActionUpdate
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
                        elif issubclass(item, ActionUpdate) and item != ActionUpdate:
                            register_update_model(item)
            except ImportError:
                # No models.py found, that's fine
                pass