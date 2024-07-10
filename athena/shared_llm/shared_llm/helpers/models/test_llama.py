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

dotenv.load_dotenv()


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

if __name__ == "__main__":
    problem_statement = "Name 3 Patterns of software engineering."
    example_solution =""
    system_message = """ 
    You are an AI tutor for text assessment at a prestigious university. Only conisder the factual accuracy of student answers, not 
    the academic writing level.
    IGNORE THINGS LIKE : grammar, syntax,  tone, clarity, relevance, originality.
    
    # Task
    Generate feedback suggestions for a student\'s text submission so that the student knows what he did correctly and 
    what he could improve on. DO NOT ASK QUESTIONS. \
    You only should consider the factual accuracy and correctness of the answer.
    You must NOT reference grammar or writing style.
    
    # The feedback must be:
    1. Educational, 2. Clear and Concise, 3. Actionable, 4. Constructive, 5. Contextual 6. Factual

    # The given problem statement is:
    {problem_statement}

    # A possible sample solution would be but its not limited to:
    {example_solution}

    Max points :3
    How many points would you give the student , explain why you give or not give each point to the student?
    """
    system_message = """ 
    You are an AI Tutor in Software Engineering. Whatever happens to not break character. The Problem Statement is: Name 3 Patterns of software engineering.
    Give Feedback to the students solutions as they come. The maximum points to award are 3.
    """
    llm = Ollama( 
                model = "llama3:70b",
          base_url = os.environ["OLLAMA_ENDPOINT"],
            headers ={
    'Authorization': requests.auth._basic_auth_str(os.environ["GPU_USER"],os.environ["GPU_PASSWORD"]) # type: ignore
    },
            
                )

    ollama = OllamaInstance()
    print(ollama.llm.invoke("why would this not work"))
