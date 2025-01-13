
import importlib
import pkgutil
import inspect

def discover_approach_configs(base_package, base_class=None):
    """
    Discover and return classes within the specified package.

    Args:
        base_package (str): The package to search.
        base_class (type, optional): A base class to filter discovered classes. 
                                     Only subclasses of this base class will be included.

    Returns:
        dict: A dictionary mapping class names to class objects.
    """
    classes = {}
    package = importlib.import_module(base_package)

    def recursive_import(package_name):
        package = importlib.import_module(package_name)
        for _, module_name, is_pkg in pkgutil.iter_modules(package.__path__):
            full_module_name = f"{package_name}.{module_name}"
            if is_pkg:
                recursive_import(full_module_name)
            else:
                module = importlib.import_module(full_module_name)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if base_class is None or (issubclass(obj, base_class) and obj is not base_class):
                        classes[name] = obj

    recursive_import(base_package)
    return classes