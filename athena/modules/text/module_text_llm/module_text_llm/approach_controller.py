from typing import List
from athena.text import Exercise, Submission, Feedback
from module_text_llm.basic_approach import BasicApproachConfig
from module_text_llm.chain_of_thought_approach import ChainOfThoughtConfig
from module_text_llm.approach_config import ApproachConfig

from module_text_llm.basic_approach.generate_suggestions import generate_suggestions as generate_suggestions_basic
from module_text_llm.chain_of_thought_approach.generate_suggestions import generate_suggestions as generate_cot_suggestions
import importlib
import pkgutil
import inspect

def discover_approach_configs(base_package="modules/text/module_text_llm/module_text_llm"):
    configs = {}
    package = importlib.import_module(base_package)
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{base_package}.{module_name}")
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, ApproachConfig) and obj is not ApproachConfig:
                configs[obj.__name__] = obj
    return configs

async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool) -> List[Feedback]:
    # print(discover_approach_configs())
    return []
    if isinstance(config, BasicApproachConfig):
        return await generate_suggestions_basic(exercise, submission, config, debug)
    if isinstance(config, ChainOfThoughtConfig):
        return await generate_cot_suggestions(exercise, submission, config, debug)
    raise ValueError("Unsupported config type provided.")
