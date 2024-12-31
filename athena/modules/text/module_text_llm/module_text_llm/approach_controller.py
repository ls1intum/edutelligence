from typing import List
from athena.text import Exercise, Submission, Feedback
# from module_text_llm.basic_approach import BasicApproachConfig
# from module_text_llm.chain_of_thought_approach import ChainOfThoughtConfig
from module_text_llm.approach_config import ApproachConfig

# from module_text_llm.basic_approach.generate_suggestions import generate_suggestions as generate_suggestions_basic
# from module_text_llm.chain_of_thought_approach.generate_suggestions import generate_suggestions as generate_cot_suggestions
import importlib
import pkgutil
import inspect
from typing import Dict

def discover_approach_configs(base_package="module_text_llm"):
    configs = {}
    package = importlib.import_module(base_package)
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{base_package}.{module_name}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, ApproachConfig) and obj is not ApproachConfig:
                configs[obj.__name__] = obj
                print("name ", name)
                print("module ",module)
    return configs

class SuggestionStrategyFactory:
    _strategies = {}

    @staticmethod
    def discover_and_initialize_strategies(base_package="module_text_llm"):
        """
        Discover all strategy classes dynamically and initialize the factory.
        """
        strategies = {}
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
                        strategies[name] = obj

        recursive_import(base_package)
        return strategies

    @staticmethod
    def initialize_strategies():
        if not SuggestionStrategyFactory._strategies:
            configs = discover_approach_configs()  # Assuming this function is defined
            strategies = SuggestionStrategyFactory.discover_and_initialize_strategies()

            for config_name, config_class in configs.items():
                strategy_class_name = config_name
                strategy_class = strategies.get(strategy_class_name)
                if strategy_class:
                    SuggestionStrategyFactory._strategies[config_name] = strategy_class

    @staticmethod
    def get_strategy(config):
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

