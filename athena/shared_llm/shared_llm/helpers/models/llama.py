import requests
from requests.auth import HTTPBasicAuth
import json
from enum import Enum
from langchain_community.llms import Ollama # type: ignore
import dotenv
from langchain_core.prompts import ChatPromptTemplate
from shared_llm.helpers.models.model_config import ModelConfig # type: ignore
from pydantic import validator, Field, PositiveInt
from langchain.base_language import BaseLanguageModel
import os
from langchain_community.chat_models import ChatOllama # type: ignore
import base64

if(os.environ["GPU_USER"] and os.environ["GPU_PASSWORD"]):
    auth_header= {
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    }
  
ollama_models = [
    'falcon:180b',
    'llama3:70b',
    'llama3:70b-instruct',
    'llama3:70b-text',
    'llava:13b',
    'llava:34b',
    'llava:7b',
    'llava-llama3:8b',
]

available_models = {}

if([os.environ["OLLAMA_ENDPOINT"]]):
    available_models = {
        name : ChatOllama(
            name = name,
            model = name,
            base_url = os.environ["OLLAMA_ENDPOINT"],
            headers = auth_header,
            
        ) for name in ollama_models
    } 

default_model_name = "llama3:70b"
LlamaModel = Enum('LlamaModel', {name: name for name in available_models}) # type: ignore
class OllamaModelConfig(ModelConfig):
        """Ollama LLM configuration."""

        model_name: LlamaModel = Field(default=default_model_name,  # type: ignore
                                        description="The name of the model to use.")
        
        name : str =  Field(default=default_model_name,  # type: ignore
                                        description="The name of the model to use.")
        
        model : str = Field(default = "llama3:70b", description="ye dont ask me why ")
        
        max_tokens: PositiveInt = Field(1000, description="")

        temperature: float = Field(default=0.0, ge=0, le=2, description="")

        top_p: float = Field(default=1, ge=0, le=1, description="")
        
        headers : dict = Field(default= auth_header, description="headers for authentication") 
        
        presence_penalty: float = Field(default=0, ge=-2, le=2, description="")

        frequency_penalty: float = Field(default=0, ge=-2, le=2, description="")

        base_url : str = Field(default="https://gpu-artemis.ase.cit.tum.de/ollama", description="")
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
                print( attr , " ", value)
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
            #TODO just add the missing kwards to the class
            allowed_fields = set(self.__fields__.keys())
            filtered_kwargs = {k: v for k, v in kwargs.items() if k in allowed_fields}
            # print(kwargs)
            # Initialize a copy of the model using the filtered kwargs
            model = model.__class__(**filtered_kwargs)

            # Initialize a copy of the model using the config
            #model = model.__class__(**kwargs)
            return model


        class Config:
            title = 'Ollama'