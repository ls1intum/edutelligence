import requests
from requests.auth import HTTPBasicAuth
import json
from enum import Enum
from langchain_community.llms import Ollama # type: ignore
import dotenv
from langchain_core.prompts import ChatPromptTemplate
from pydantic import validator, Field, PositiveInt
from langchain.base_language import BaseLanguageModel
import os
from langchain_community.chat_models import ChatOllama # type: ignore
from model_config import ModelConfig # type: ignore

dotenv.load_dotenv()
# Define the URL
url = 'https://gpu-artemis.ase.cit.tum.de/ollama/api/generate'
ollama_endpoint = 'https://gpu-artemis.ase.cit.tum.de/ollama'

auth = HTTPBasicAuth(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"])

headers2={
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    }
sys_mes = """
You are an AI tutor for text assessment at a prestigious university.
\n\n# Task\nCreate graded feedback suggestions for a student's 
text submission that a human tutor would accept. Meaning, the
feedback you provide should be applicable to the submission 
with little to no modification.\n\n# Style\n1. Constructive, 2.
Specific, 3. Balanced, 4. Clear and Concise, 5. Actionable, 6. 
Educational, 7. Contextual\n\n# Problem statement\nName three patterns 
in software engineering\n\n# Example solution\nSE Patterns include for
example: MVC, Proxy, Command, Adapter, Bridge, Strategy, Composite, State,
Observer, Abstract Factory, Repository, Blackboard, Layered Architecture,
Client-Server...\n\n# Grading instructions\nFor every correct pattern, give 
1 point.\nMax points: 3.0, bonus points: 0.0\nThe output should be formatted 
as a JSON instance that conforms to the JSON schema below.\n\nAs an example, 
for the schema {\"properties\": {\"foo\": {\"title\": \"Foo\", \"description\":
\"a list of strings\", \"type\": \"array\", \"items\": {\"type\": \"string\"}}},
\"required\": [\"foo\"]}\nthe object {\"foo\": [\"bar\", \"baz\"]} is a well-formatted 
instance of the schema. The object {\"properties\": {\"foo\": [\"bar\", \"baz\"]}} is 
not well-formatted.\n\nHere is the output schema:\n```\n{\"$defs\": {\"FeedbackModel\": 
{\"properties\": {\"title\": {\"description\": \"Very short title, i.e. feedback category
or similar\", \"example\": \"Logic Error\", \"title\": \"Title\", \"type\": \"string\"}, 
\"description\": {\"description\": \"Feedback description\", \"title\": \"Description\", 
\"type\": \"string\"}, \"line_start\": {\"anyOf\": [{\"type\": \"integer\"}, {\"type\": 
\"null\"}], \"description\": \"Referenced line number start, or empty if unreferenced\",
\"title\": \"Line Start\"}, \"line_end\": {\"anyOf\": [{\"type\": \"integer\"}, {\"type\
    ": \"null\"}], \"description\": \"Referenced line number end, or empty if unreferenced\", 
    \"title\": \"Line End\"}, \"credits\": {\"default\": 0.0, \"description\": \"Number of 
    points received/deducted\", \"title\": \"Credits\", \"type\": \"number\"}, 
    \"grading_instruction_id\": {\"anyOf\": [{\"type\": \"integer\"}, {\"type\": \"null\"}], 
    \"description\": \"ID of the grading instruction that was used to generate this feedback,
    or empty if no grading instruction was used\", \"title\": \"Grading Instruction Id\"}}, 
    \"required\": [\"title\", \"description\", \"line_start\", \"line_end\", 
    \"grading_instruction_id\"], \"title\": \"Feedback\", \"type\": \"object\"}}, 
    \"description\": \"Collection of feedbacks making up an assessment\", \"properties\": 
    {\"feedbacks\": {\"description\": \"Assessment feedbacks\", \"items\": {\"$ref\":
    \"#/$defs/FeedbackModel\"}, \"title\": \"Feedbacks\", \"type\": \"array\"}}, \"required\":
    [\"feedbacks\"]}\n```"
"""
system_message = """ 
You are an AI Tutor in Software Engineering. Whatever happens to not break character. The Problem Statement is: Name 3 Patterns of software engineering.
Give Feedback to the students solutions as they come. The maximum points to award are 3.
"""
llm = ChatOllama( 
            model = "llama3:70b",
           # system = system_message,
         base_url = os.environ["OLLAMA_ENDPOINT"],
            headers ={
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    },
            )
 
# Set the authentication

# Send the POST request
""" This is calling ollama programmatically but like in a curl equivalent way.
Most likely we will use the langchain way of calling ollama, which tbh is similar but whatevs
"""
def call_ollama(system_message, prompt):
    #from requests.auth import HTTPBasicAuth

    url = 'https://gpu-artemis.ase.cit.tum.de/ollama/api/generate'
    auth = HTTPBasicAuth(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"])
    # Define the data payload
    payload = {
        "model": "llama3:70b",
        "system" : system_message,
        "prompt": prompt,
        "options" : {
            "top_k": 10,
            "top_p": 0.95,
            "repeat_penalty": 2.0,
            # "num_predict": 1000 ,
            "temperature" : 0,
        },
        "stream": False,
        "format":"json"
    }

    response = requests.post(url, json=payload, auth=auth ,stream=False)
    print(response.content)
    # response_str = response.content.decode('utf-8')

    # # Parse the JSON string into a Python dictionary
    # data = json.loads(response_str)

    # # Extract the list of models
    # text_response = data['response']
    
    # return text_response
    # # Print the response headers
    # print("Response Headers:")
    # for key, value in response.headers.items():
    #     print(f"{key}: {value}")

    # long_respnse = ""
    # print("\nResponse Content:")
    # try:
    #     for chunk in response.iter_lines():
    #         if chunk:
    #             try:
    #                 # Decode the chunk and parse it as JSON
    #                 chunk_data = json.loads(chunk.decode('utf-8'))
                    
    #                 # Extract and print the "response" part
    #                 if 'response' in chunk_data:
    #                     long_respnse +=chunk_data['response']
    #                     print(chunk_data['response'], end='', flush=True)
    #                 if 'done' in chunk_data:
    #                     if(chunk_data['done']):
    #                         break
    #             except json.JSONDecodeError as e:
    #                 print(f"\nError decoding JSON: {e}")
    # except requests.exceptions.RequestException as e:
    #     print(f"\nError during streaming: {e}")
    # finally:
    #     response.close()
    # return(response)
        # Send the POST request
        
""" This is calling ollama programmatically but like in a curl equivalent way.
Most likely we will use the langchain way of calling ollama, which tbh is similar but whatevs
"""
def get_ollama_models():
    url_list = 'https://gpu-artemis.ase.cit.tum.de/ollama/api/tags'

    response = requests.get(url_list,  auth=auth)
    # Decode the byte string to a regular string
    response_str = response.content.decode('utf-8')

    # Parse the JSON string into a Python dictionary
    data = json.loads(response_str)

    # Extract the list of models
    models = data['models']

    # Iterate over each model and print the 'model' attribute
    for model in models:
        print(model['model'])
    return(response)

def chain_of_thought():
    return 0
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
            
            model = available_models[self.model_name]
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
        return self.llm.invoke(prompt)#

def parse_ollama_calls():
    pass

if __name__ == "__main__":
    response = call_ollama(sys_mes, "Observer pattern and other patterns")
    # print(response)
    # response_str = response.content.decode('utf-8')

    # # Parse the JSON string into a Python dictionary
    # data = json.loads(response_str)

    # # Extract the list of models
    # models = data['response']
    # print(models)
    # stuff = OllamaModelConfig()
    # model = stuff.get_model()
    # print(model.invoke("yo what up llama"))
    # get_ollama_models()
    # problem_statement = "Name 3 Patterns of software engineering."
    # example_solution =""
    # system_message = """ 
    # You are an AI tutor for text assessment at a prestigious university. Only conisder the factual accuracy of student answers, not 
    # the academic writing level.
    # IGNORE THINGS LIKE : grammar, syntax,  tone, clarity, relevance, originality.
    
    # # Task
    # Generate feedback suggestions for a student\'s text submission so that the student knows what he did correctly and 
    # what he could improve on. DO NOT ASK QUESTIONS. \
    # You only should consider the factual accuracy and correctness of the answer.
    # You must NOT reference grammar or writing style.
    
    # # The feedback must be:
    # 1. Educational, 2. Clear and Concise, 3. Actionable, 4. Constructive, 5. Contextual 6. Factual

    # # The given problem statement is:
    # {problem_statement}

    # # A possible sample solution would be but its not limited to:
    # {example_solution}

    # Max points :3
    # How many points would you give the student , explain why you give or not give each point to the student?
    # """
    # system_message = """ 
    # You are an AI Tutor in Software Engineering. Whatever happens to not break character. The Problem Statement is: Name 3 Patterns of software engineering.
    # Give Feedback to the students solutions as they come. The maximum points to award are 3.
    # """
    # llm = Ollama( 
    #             model = "llama3:70b",
    #       base_url = os.environ["OLLAMA_ENDPOINT"],
    #         headers ={
    # 'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    # },
            
    #             )

    # ollama = OllamaInstance()
    # print(ollama.llm.invoke("why would this not work"))
