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

dotenv.load_dotenv()

class OllamaInstance():
    auth = HTTPBasicAuth(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"])
    headers2={
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    }
    ollama_endpoint = 'https://gpu-artemis.ase.cit.tum.de/ollama'
    
    
    def __init__(self):
        self.llm = Ollama( 
            model = "llama3:70b",
           # system = system_message,
            base_url = ollama_endpoint,
            headers =headers2,
            temperature = 1,
            mirostat =2,
            top_p = 1,
            )
        
    def get_llama_llama(self):
        return self.llm
    
    def invoke_this_thing(self, prompt):
        return self.llm.invoke(prompt)
    
# Define the URL
url = 'https://gpu-artemis.ase.cit.tum.de/ollama/api/generate'
ollama_endpoint = 'https://gpu-artemis.ase.cit.tum.de/ollama'
auth = HTTPBasicAuth(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"])



headers2={
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    }

system_message = """ 
You are an AI Tutor in Software Engineering. Whatever happens to not break character. The Problem Statement is: Name 3 Patterns of software engineering.
Give Feedback to the students solutions as they come. The maximum points to award are 3.
"""
llm = ChatOllama( 
            model = "llama3:70b",
           # system = system_message,
            base_url = ollama_endpoint,
            headers =headers2,
            temperature = 1,
            mirostat =2,
            top_p = 1,
            )
 
# Set the authentication

# Send the POST request
""" This is calling ollama programmatically but like in a curl equivalent way.
Most likely we will use the langchain way of calling ollama, which tbh is similar but whatevs
"""
def call_ollama(system_message, prompt):
    # Define the data payload
    payload = {
        "model": "llama3:70b",
        "system" : system_message,
        "prompt": prompt,
        "options" : {
            "top_k": 10,
            "top_p": 0.95,
            "repeat_penalty": 2.0,
            "num_predict": 1000 ,
            "temperature" : 0.1,
        } 
    }

    response = requests.post(url, json=payload, auth=auth ,stream=True)

    # Print the response headers
    print("Response Headers:")
    for key, value in response.headers.items():
        print(f"{key}: {value}")

    long_respnse = ""
    print("\nResponse Content:")
    try:
        for chunk in response.iter_lines():
            if chunk:
                try:
                    # Decode the chunk and parse it as JSON
                    chunk_data = json.loads(chunk.decode('utf-8'))
                    
                    # Extract and print the "response" part
                    if 'response' in chunk_data:
                        long_respnse +=chunk_data['response']
                        print(chunk_data['response'], end='', flush=True)
                    if 'done' in chunk_data:
                        if(chunk_data['done']):
                            break
                except json.JSONDecodeError as e:
                    print(f"\nError decoding JSON: {e}")
    except requests.exceptions.RequestException as e:
        print(f"\nError during streaming: {e}")
    finally:
        response.close()
    return(long_respnse)
        

def chain_of_thought():
    return 0


class OllamaModelConfig(ModelConfig):
        #LlamaModel = Enum('LlamaModel', {"llama3:70b": "llama3:70b"})  # type: ignore

        """OpenAI LLM configuration."""

        model_name: str = Field(default="mr llama",  # type: ignore
                                        description="The name of the model to use.")
        max_tokens: PositiveInt = Field(1000, description="")

        temperature: float = Field(default=0.0, ge=0, le=2, description="")

        top_p: float = Field(default=1, ge=0, le=1, description="")

        presence_penalty: float = Field(default=0, ge=-2, le=2, description="")

        frequency_penalty: float = Field(default=0, ge=-2, le=2, description="")

        @validator('max_tokens')
        def max_tokens_must_be_positive(cls, v):
            """
            Validate that max_tokens is a positive integer.
            """
            if v <= 0:
                raise ValueError('max_tokens must be a positive integer')
            return v
        
        def get_model_name(self) -> str:
            """Get the model name from the configuration."""
            return self.model_name
        
        def get_model(self) -> BaseLanguageModel:
            """Get the model from the configuration.

            Returns:
                BaseLanguageModel: The model.
            """
            #return llm
            
            model = llm # "llama3:70b" #available_models[self.model_name.value]
            kwargs = model.__dict__ #BaseLanguageModel type
            #kwargs = model._lc_kwargs
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
            title = 'Ollama'