import os
import openai
import requests

from typing import Dict, List
from enum import Enum
from pydantic import Field, validator, PositiveInt
from langchain.base_language import BaseLanguageModel
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from athena.logger import logger
from .model_config import ModelConfig

OPENAI_PREFIX = "openai_"
AZURE_OPENAI_PREFIX = "azure_openai_"
openai_available = bool(os.environ.get("OPENAI_API_KEY"))
azure_openai_available = bool(os.environ.get("AZURE_OPENAI_API_KEY"))

available_models: Dict[str, BaseLanguageModel] = {}

# Load Non-Azure OpenAI models
if openai_available:
    openai.api_type = "openai"
    for model in openai.models.list():
        if "gpt" in model.id:
            available_models[OPENAI_PREFIX + model.id] = ChatOpenAI(model=model.id)

# Load Azure OpenAI models
if azure_openai_available:
    def _get_azure_openai_deployments() -> List[str]:
        # If this breaks in the future we have to use azure-mgmt-cognitiveservices which needs 6 additional environment variables
        base_url = f"{os.environ.get('AZURE_OPENAI_ENDPOINT')}/openai"
        headers = {
            "api-key": os.environ["AZURE_OPENAI_API_KEY"]
        }

        models_response = requests.get(f"{base_url}/models?api-version=2023-03-15-preview", headers=headers, timeout=60)
        models_data = models_response.json()["data"]
        deployments_response = requests.get(f"{base_url}/deployments?api-version=2023-03-15-preview", headers=headers, timeout=60)
        deployments_data = deployments_response.json()["data"]

        # Check if deployment["model"] is a substring of model["id"], i.e. "gpt-4o" is substring "gpt-4o-2024-05-13"
        chat_completion_models = ",".join(model["id"] for model in models_data if model["capabilities"]["chat_completion"])
        return [deployment["id"] for deployment in deployments_data if deployment["model"] in chat_completion_models]

    for deployment in _get_azure_openai_deployments():
        available_models[AZURE_OPENAI_PREFIX + deployment] = AzureChatOpenAI(azure_deployment=deployment)

if available_models:
    logger.info("Available openai models: %s", ", ".join(available_models.keys()))

    OpenAIModel = Enum('OpenAIModel', {name: name for name in available_models}) # type: ignore
    default_model_name = None
    if "LLM_DEFAULT_MODEL" in os.environ and os.environ["LLM_DEFAULT_MODEL"] in available_models:
        default_model_name = os.environ["LLM_DEFAULT_MODEL"]
    if default_model_name not in available_models:
        default_model_name = list(available_models.keys())[0]

    default_openai_model = OpenAIModel[default_model_name] # type: ignore

    # Long descriptions will be displayed in the playground UI and are copied from the OpenAI docs
    class OpenAIModelConfig(ModelConfig):
        """OpenAI LLM configuration."""

        model_name: OpenAIModel = Field(default=default_openai_model, # type: ignore
                                        description="The name of the model to use.")
        max_tokens: PositiveInt = Field(1000, description="""\
The maximum number of [tokens](https://platform.openai.com/tokenizer) to generate in the chat completion.

The total length of input tokens and generated tokens is limited by the model's context length. \
[Example Python code](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb) for counting tokens.\
""")

        temperature: float = Field(default=0.0, ge=0, le=2, description="""\
What sampling temperature to use, between 0 and 2. Higher values like 0.8 will make the output more random, \
while lower values like 0.2 will make it more focused and deterministic.

We generally recommend altering this or `top_p` but not both.\
""")

        top_p: float = Field(default=1, ge=0, le=1, description="""\
An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top_p probability mass. \
So 0.1 means only the tokens comprising the top 10% probability mass are considered.

We generally recommend altering this or `temperature` but not both.\
""")

        presence_penalty: float = Field(default=0, ge=-2, le=2, description="""\
Number between -2.0 and 2.0. Positive values penalize new tokens based on whether they appear in the text so far, \
increasing the model's likelihood to talk about new topics.

[See more information about frequency and presence penalties.](https://platform.openai.com/docs/api-reference/parameter-details)\
""")

        frequency_penalty: float = Field(default=0, ge=-2, le=2, description="""\
Number between -2.0 and 2.0. Positive values penalize new tokens based on their existing frequency in the text so far, \
decreasing the model's likelihood to repeat the same line verbatim.

[See more information about frequency and presence penalties.](https://platform.openai.com/docs/api-reference/parameter-details)\
""")

        @validator('max_tokens')
        def max_tokens_must_be_positive(cls, v):
            """
            Validate that max_tokens is a positive integer.
            """
            if v <= 0:
                raise ValueError('max_tokens must be a positive integer')
            return v

        def get_model(self) -> BaseLanguageModel:
            """Get the model from the configuration.

            Returns:
                BaseLanguageModel: The model.
            """
            model = available_models[self.model_name.value]
            kwargs = model.__dict__
            secrets = {secret: getattr(model, secret) for secret in model.lc_secrets.keys()}
            kwargs.update(secrets)

            model_kwargs = kwargs.get("model_kwargs", {})
            for attr, value in self.dict().items():
                if attr == "model_name":
                    # Skip model_name
                    continue
                if hasattr(model, attr):
                    # If the model has the attribute, add it to kwargs
                    kwargs[attr] = value
                else:
                    # Otherwise, add it to model_kwargs (necessary for chat models)
                    model_kwargs[attr] = value
            kwargs["model_kwargs"] = model_kwargs

            # Initialize a copy of the model using the config
            model = model.__class__(**kwargs)
            return model


        class Config:
            title = 'OpenAI'