from module_text_llm.approach_config import ApproachConfig
from pydantic import Field
from typing import Literal


from module_text_llm.basic_approach.prompt_generate_suggestions import GenerateSuggestionsPrompt

class BasicApproachConfig(ApproachConfig):
    type: Literal['basic'] = 'basic'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())

