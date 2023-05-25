"""Dynamically generate an enum for the available modules, based on the modules.ini file."""
from enum import Enum

from .list_modules import list_modules


def get_module_names_with_docs() -> dict:
    modules = list_modules()
    module_names_with_docs = {}
    for module in modules:
        module_doc = f"{module.name} ({module.url}, {module.type})"
        module_names_with_docs[module.name] = (module.name, module_doc)
    return module_names_with_docs


AvailableModuleNames = Enum(  # type: ignore
    "AvailableModuleNames",
    {name: value for name, (value, _) in get_module_names_with_docs().items()},
    type=str,
    module=__name__,
    qualname="AvailableModuleNames",
)
AvailableModuleNames.__doc__ = "An available module name, as specified in modules.ini in the Assessment module Manager."

for name, (value, doc) in get_module_names_with_docs().items():
    setattr(AvailableModuleNames[name], "__doc__", doc)
