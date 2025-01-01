from typing import List
from athena.text import Exercise, Submission, Feedback
from module_text_llm.approach_config import ApproachConfig
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


class SuggestionStrategyFactory:
    """
    A factory class for discovering, initializing, and retrieving suggestion strategies.

    The `SuggestionStrategyFactory` dynamically loads strategy classes, associates them with 
    specific configuration types, and provides instances of the strategies based on the given 
    configuration. It supports modular discovery and initialization to handle a variety of 
    strategies seamlessly.

    Attributes:
        _strategies (dict): A dictionary mapping configuration class names to their corresponding strategy classes.
    """
    _strategies = {}

    @staticmethod
    def initialize_strategies(base_package="module_text_llm"):
        """
        Initialize the factory by associating configuration types with their corresponding strategies.

        This method uses the `discover_classes` function to identify configuration classes and their 
        associated strategies. The mappings are stored in the `_strategies` dictionary for later retrieval.

        Args:
            base_package (str): The base package to search for strategies and configurations. 
                                Defaults to "module_text_llm".
        """
        if not SuggestionStrategyFactory._strategies:
            configs = discover_approach_configs(base_package, base_class=ApproachConfig)
            # strategies = discover_approach_configs(base_package)

            for config_name, config_class in configs.items():
                strategy_class = configs.get(config_name)
                if strategy_class:
                    SuggestionStrategyFactory._strategies[config_name] = strategy_class

    @staticmethod
    def get_strategy(config):
        """
        Retrieve an instance of the strategy corresponding to the given configuration.

        If the strategies have not been initialized, this method will initialize them first.
        The method then matches the type of the provided configuration with the corresponding 
        strategy class and returns an instance of it.

        Args:
            config (object): The configuration object for which the strategy is required.

        Returns:
            object: An instance of the strategy class associated with the given configuration.

        Raises:
            ValueError: If no strategy is found for the given configuration type.
        """
        if not SuggestionStrategyFactory._strategies:
            SuggestionStrategyFactory.initialize_strategies()

        config_type = type(config).__name__
        strategy_class = SuggestionStrategyFactory._strategies.get(config_type)
        if not strategy_class:
            raise ValueError(f"No strategy found for config type: {config_type}")
        return strategy_class()

async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool) -> List[Feedback]:
    strategy = SuggestionStrategyFactory.get_strategy(config)
    return await strategy.generate_suggestions(exercise, submission, config, debug)

