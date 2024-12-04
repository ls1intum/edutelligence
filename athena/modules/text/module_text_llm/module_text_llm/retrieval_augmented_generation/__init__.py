from module_text_llm.approach_config import ApproachConfig
from pydantic import Field
from typing import Literal
from module_text_llm.retrieval_augmented_generation.agents import TutorAgent
from module_text_llm.retrieval_augmented_generation.prompt_generate_suggestions import GenerateSuggestionsPrompt

tutor = TutorAgent()

class RAGApproachConfig(ApproachConfig):
    type: Literal['rag'] = 'rag'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())
    