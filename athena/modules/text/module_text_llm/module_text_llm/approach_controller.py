from typing import List
from athena.text import Exercise, Submission, Feedback
from module_text_llm.basic_approach import BasicApproachConfig
from module_text_llm.chain_of_thought_approach import ChainOfThoughtConfig
from module_text_llm.ollama_chain_of_thought_approach import OllamaChainOfThoughtConfig
from module_text_llm.approach_config import ApproachConfig

from module_text_llm.basic_approach.generate_suggestions import generate_suggestions as generate_suggestions_basic
from module_text_llm.chain_of_thought_approach.generate_suggestions import generate_suggestions as generate_cot_suggestions
from module_text_llm.ollama_chain_of_thought_approach.generate_suggestions import generate_suggestions as generate_cot_ollana_suggestions
async def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool) -> List[Feedback]:
    if isinstance(config, BasicApproachConfig):
        return await generate_suggestions_basic(exercise, submission, config, debug)
    if isinstance(config, ChainOfThoughtConfig):
        return await generate_cot_suggestions(exercise, submission, config, debug)
    if isinstance(config, OllamaChainOfThoughtConfig):
        return await generate_cot_ollana_suggestions(exercise, submission, config, debug)
    raise ValueError("Unsupported config type provided.")
