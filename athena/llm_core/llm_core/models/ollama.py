import requests
from enum import Enum
from llm_core.models.model_config import ModelConfig # type: ignore
from pydantic import validator, Field, PositiveInt
from langchain.base_language import BaseLanguageModel
import os
from langchain_community.chat_models import ChatOllama # type: ignore
from athena.logger import logger
from requests.exceptions import RequestException, Timeout

if os.environ.get('GPU_USER') and os.environ.get('GPU_PASSWORD') and os.environ.get('OLLAMA_ENDPOINT')   is not None:
    try:
        if(os.environ["GPU_USER"] and os.environ["GPU_PASSWORD"]):
            auth_header= {
            'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
            }


        def get_ollama_models():
            url = os.environ["OLLAMA_ENDPOINT"] + "/api/tags"
            response = requests.get(url, auth=(os.environ["GPU_USER"], os.environ["GPU_PASSWORD"]))
            data = response.json()
            model_list = [model['name'] for model in data['models']]
            return model_list

        ollama_models = get_ollama_models()
        available_models = {}

        if([os.environ["OLLAMA_ENDPOINT"]]):
            available_models = {
                name : ChatOllama(
                    name = name,
                    model = name,
                    base_url = os.environ["OLLAMA_ENDPOINT"],
                    headers = auth_header,
                    format = "json"
                ) for name in ollama_models
            } 

        default_model_name = "llama3.3:latest"
        LlamaModel = Enum('LlamaModel', {name: name for name in available_models}) # type: ignore
        class OllamaModelConfig(ModelConfig):
                """Ollama LLM configuration."""
                logger.info("Available ollama models: %s", ", ".join(available_models.keys()))

                model_name: LlamaModel = Field(default=default_model_name,  # type: ignore
                                                description="The name of the model to use.")
                
                format : str = Field(default = "json" , description="The format to respond with")
                
                max_tokens: PositiveInt = Field(1000, description="")

                temperature: float = Field(default=0.0, ge=0, le=2, description="")

                top_p: float = Field(default=1, ge=0, le=1, description="")
                
                headers : dict = Field(default= auth_header, description="headers for authentication") 
                
                presence_penalty: float = Field(default=0, ge=-2, le=2, description="")

                frequency_penalty: float = Field(default=0, ge=-2, le=2, description="")

                base_url : str = Field(default="https://gpu-artemis.ase.cit.tum.de/ollama", description=" Base Url where ollama is hosted")
                @validator('max_tokens')
                def max_tokens_must_be_positive(cls, v):
                    """
                    Validate that max_tokens is a positive integer.
                    """
                    if v <= 0:
                        raise ValueError('max_tokens must be a positive integer')
                    return v
                
                def get_model(self) -> BaseLanguageModel:
                    logger.info("Getting Model: ", self.model_name.value)
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

                    allowed_fields = set(self.__fields__.keys())
                    filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_fields}
                    filtered_kwargs["headers"] = auth_header
                    filtered_kwargs["model"]= self.model_name.value

                    # Initialize a copy of the model using the filtered kwargs
                    model = model.__class__(**filtered_kwargs)

                    return model


                class Config:
                    title = 'Ollama'
    except Timeout:
        logger.info("Connection timed out. Skipping gpu server connection step.")
    except RequestException as e:
        logger.info(f"Failed to connect to the gpu server: {e}. Skipping this step.")
        