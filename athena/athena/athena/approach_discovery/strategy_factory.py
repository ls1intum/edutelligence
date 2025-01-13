from athena.approach_discovery.discover_approaches import discover_approach_configs
from typing import List, Callable

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
    _strategies: dict[str, Callable] = {}
    def __init__(self, base_package: str, base_class: type):
        """
        Initialize the factory by providing the base package and base class for discovering strategies.

        Args:
            base_package (str): The base package to search for strategies and configurations.
            base_class (type): The base class for configurations that strategies will be associated with.
        """
        self.base_package = base_package
        self.base_class = base_class

        # Initialize strategies on object creation
        self.initialize_strategies()
    
    def initialize_strategies(self):
        """
        Initialize the factory by associating configuration types with their corresponding strategies.

        This method uses the `discover_classes` function to identify configuration classes and their 
        associated strategies. The mappings are stored in the `_strategies` dictionary for later retrieval.

        Args:
            base_package (str): The base package to search for strategies and configurations. 
                                Defaults to "module_text_llm".
        """
        if not SuggestionStrategyFactory._strategies:
            configs = discover_approach_configs(self.base_package, base_class=self.base_class)
            # strategies = discover_approach_configs(base_package)

            for config_name, config_class in configs.items():
                strategy_class = configs.get(config_name)
                if strategy_class:
                    SuggestionStrategyFactory._strategies[config_name] = strategy_class

    
    def get_strategy(self, config):
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
        # if not SuggestionStrategyFactory._strategies:
        #     self.initialize_strategies()

        config_type = type(config).__name__
        strategy_class = SuggestionStrategyFactory._strategies.get(config_type)
        if not strategy_class:
            raise ValueError(f"No strategy found for config type: {config_type}")
        return strategy_class()