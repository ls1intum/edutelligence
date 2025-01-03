from llm_core.loaders.openai_loader import OpenAIModel
from llm_core.loaders.llm_capabilities_loader import get_model_capabilities
from pydantic import Field, PrivateAttr, validator, PositiveInt
from langchain.base_language import BaseLanguageModel
from llm_core.loaders.openai_loader import available_models

from ..model_config import ModelConfig
from ..usage_handler import UsageHandler

class OpenAIModelConfig(ModelConfig):
    """OpenAI LLM configuration."""

    model_name: OpenAIModel = Field(
        description="The name of the model to use (e.g., openai_gpt-3.5-turbo)."
    )

    max_completion_tokens: PositiveInt = Field(
        4000,
        description="An upper bound for the number of tokens that can be generated for a completion, including visible output tokens and reasoning tokens."
    )

    temperature: float = Field(
        default=0.0, ge=0, le=2, 
        description="""\
What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, 
while lower values like 0.2 will make it more focused and deterministic.

We generally recommend altering this or `top_p` but not both.\
"""
    )

    top_p: float = Field(
        default=1, ge=0, le=1, 
        description="""\
An alternative to sampling with temperature, called nucleus sampling, where the model considers the results 
of the tokens with top_p probability mass. So 0.1 means only the tokens comprising the top 10% probability 
mass are considered.

We generally recommend altering this or `temperature` but not both.\
"""
    )

    presence_penalty: float = Field(
        default=0, ge=-2, le=2, 
        description="""\
Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, 
increasing the model's likelihood to talk about new topics.

[See more information about frequency and presence penalties.](https://platform.openai.com/docs/api-reference/parameter-details)\
"""
    )

    frequency_penalty: float = Field(
        default=0, ge=-2, le=2, 
        description="""\
Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, 
decreasing the model's likelihood to repeat the same line verbatim.

[See more information about frequency and presence penalties.](https://platform.openai.com/docs/api-reference/parameter-details)\
"""
    )

    # Private boolean flags
    _supports_function_calling: bool = PrivateAttr(default=True)
    _supports_structured_output: bool = PrivateAttr(default=True)
    _supports_system_messages: bool = PrivateAttr(default=True)

    # Initialization: Merge YAML capabilities
    def __init__(self, **data):
        super().__init__(**data)
        raw_key = self.model_name.value if hasattr(self.model_name, "value") else self.model_name
        caps = get_model_capabilities(raw_key)

        fields_set_by_user = set(data.keys())

        # If user didn't pass a certain field, override from YAML
        if "temperature" not in fields_set_by_user and "temperature" in caps:
            self.temperature = float(caps["temperature"])
        if "top_p" not in fields_set_by_user and "top_p" in caps:
            self.top_p = float(caps["top_p"])
        if "presence_penalty" not in fields_set_by_user and "presence_penalty" in caps:
            self.presence_penalty = float(caps["presence_penalty"])
        if "frequency_penalty" not in fields_set_by_user and "frequency_penalty" in caps:
            self.frequency_penalty = float(caps["frequency_penalty"])
        if "max_completion_tokens" not in fields_set_by_user and "max_completion_tokens" in caps:
            self.max_completion_tokens = caps["max_completion_tokens"]

        # set booleans from caps
        self._supports_function_calling = bool(caps.get("supports_function_calling", True))
        self._supports_structured_output = bool(caps.get("supports_structured_output", True))
        self._supports_system_messages = bool(caps.get("supports_system_messages", True))

    def supports_system_messages(self) -> bool:
        return self._supports_system_messages

    def supports_function_calling(self) -> bool:
        return self._supports_function_calling

    def supports_structured_output(self) -> bool:
        return self._supports_structured_output

    @validator('max_completion_tokens')
    def max_completion_tokens_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('max_completion_tokens must be a positive integer')
        return v

    def get_model(self) -> BaseLanguageModel:
        """
        Create the ChatOpenAI/AzureChatOpenAI object.
        Only add parameters that the model actually supports.
        """
        model = available_models[self.model_name.value]
        kwargs = model.__dict__.copy()

        secrets = {secret: getattr(model, secret) for secret in model.lc_secrets.keys()}
        kwargs.update(secrets)

        model_kwargs = kwargs.get("model_kwargs", {})

        for attr, value in self.dict().items():
            if attr == "model_name":
                continue 
            if hasattr(model, attr):
                kwargs[attr] = value
            else:
                model_kwargs[attr] = value


        kwargs["model_kwargs"] = model_kwargs
        kwargs["callbacks"] = [UsageHandler()]

        new_model = model.__class__(**kwargs)
        return new_model

    class Config:
        title = 'OpenAI'