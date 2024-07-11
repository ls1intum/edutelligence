from typing import Optional, Type, TypeVar, List
#from pydantic import BaseModel, ValidationError
from langchain_community.llms import Ollama # type: ignore
from langchain_community.chat_models import ChatOllama # type: ignore
from langchain_core.messages.base import BaseMessage
from langchain_core.messages import HumanMessage, SystemMessage
from requests.auth import HTTPBasicAuth
import json
import os
import requests
import tiktoken
from langchain_core.output_parsers.openai_functions import JsonOutputFunctionsParser
from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_openai.chat_models.base import BaseChatOpenAI
from pydantic import BaseModel, ValidationError
import tiktoken
from langchain_openai import AzureChatOpenAI, AzureOpenAI, ChatOpenAI

from langchain.base_language import BaseLanguageModel
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.output_parsers import PydanticOutputParser
from langchain.schema import (
    OutputParserException
)

from langchain.chains import LLMChain

from athena import emit_meta, get_experiment_environment

T = TypeVar("T", bound=BaseModel)

def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens


def num_tokens_from_prompt(chat_prompt: ChatPromptTemplate, prompt_input: dict) -> int:
    """Returns the number of tokens in a chat prompt."""
    return num_tokens_from_string(chat_prompt.format(**prompt_input))


def check_prompt_length_and_omit_features_if_necessary(prompt: ChatPromptTemplate, 
                                                       prompt_input: dict, 
                                                       max_input_tokens: int, 
                                                       omittable_features: List[str],
                                                       debug: bool):
    """Check if the input is too long and omit features if necessary.

    Note: Omitted features will be replaced with "omitted" in the prompt

    Args:
        prompt (ChatPromptTemplate): Prompt template
        prompt_input (dict): Prompt input
        max_input_tokens (int): Maximum number of tokens allowed
        omittable_features (List[str]): List of features that can be omitted, ordered by priority (least important first)
        debug (bool): Debug flag

    Returns:
        (dict, bool): Tuple of (prompt_input, should_run) where prompt_input is the input with omitted features and 
                      should_run is True if the model should run, False otherwise
    """
    if num_tokens_from_prompt(prompt, prompt_input) <= max_input_tokens:
        # Full prompt fits into LLM context => should run with full prompt
        return prompt_input, True

    omitted_features = []

    # Omit features until the input is short enough
    for feature in omittable_features:
        if feature in prompt_input:
            omitted_features.append(feature)
            prompt_input[feature] = "omitted"
            if num_tokens_from_prompt(prompt, prompt_input) <= max_input_tokens:
                if debug:
                    emit_meta("omitted_features", omitted_features)
                return prompt_input, True

    # If we get here, we couldn't omit enough features
    return prompt_input, False


def supports_function_calling(model: BaseLanguageModel):
    """Returns True if the model supports function calling, False otherwise

    Args:
        model (BaseLanguageModel): The model to check

    Returns:
        boolean: True if the model supports function calling, False otherwise
    """
    return isinstance(model, ChatOpenAI)

def is_azure_call(model:BaseLanguageModel):
    return isinstance(model, AzureChatOpenAI)

def get_chat_prompt_with_formatting_instructions(
            model: BaseLanguageModel,
            system_message: str, 
            human_message: str,
            pydantic_object: Type[T]
        ) -> ChatPromptTemplate:
    """Returns a ChatPromptTemplate with formatting instructions (if necessary)

    Note: Does nothing if the model supports function calling

    Args:
        model (BaseLanguageModel): The model to check if it supports function calling
        system_message (str): System message
        human_message (str): Human message
        pydantic_object (Type[T]): Model to parse the output

    Returns:
        ChatPromptTemplate: ChatPromptTemplate with formatting instructions (if necessary)
    """
    if supports_function_calling(model):
        system_message_prompt = SystemMessagePromptTemplate.from_template(system_message)
        human_message_prompt = HumanMessagePromptTemplate.from_template(human_message)
        return ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])
    
    output_parser = PydanticOutputParser(pydantic_object=pydantic_object)
    system_message_prompt = SystemMessagePromptTemplate.from_template(system_message + "\n{format_instructions}")
    system_message_prompt.prompt.partial_variables = {"format_instructions": output_parser.get_format_instructions()}#type: ignore
    system_message_prompt.prompt.input_variables.remove("format_instructions") #type:ignore
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_message + "\n\nJSON response following the provided schema:")
    return ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

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
            # "top_k": 10,
            # "top_p": 0.95,
            "repeat_penalty": 0,
            "temperature" : 0,
        },
        "stream": False,
        "format" : "json"
    }

    response = requests.post(url, json=payload, auth=auth ,stream=False)
    print(response)
    response_str = response.content.decode('utf-8')

    # Parse the JSON string into a Python dictionary
    data = json.loads(str(response_str))

    # Extract the list of models
    text_response = data['response']
    
    return text_response

async def predict_and_parse(
        model: BaseLanguageModel, 
        chat_prompt: ChatPromptTemplate, 
        prompt_input: dict, 
        pydantic_object: Type[T], 
        tags: Optional[List[str]]
    ) -> Optional[T]:
    print("type of model is ", type(model))
    """Predicts an LLM completion using the model and parses the output using the provided Pydantic model

    Args:
        model (BaseLanguageModel): The model to predict with
        chat_prompt (ChatPromptTemplate): Prompt to use
        prompt_input (dict): Input parameters to use for the prompt
        pydantic_object (Type[T]): Pydantic model to parse the output
        tags (Optional[List[str]]: List of tags to tag the prediction with

    Returns:
        Optional[T]: Parsed output, or None if it could not be parsed
    """
    experiment = get_experiment_environment()

    tags = tags or []
    if experiment.experiment_id is not None:
        tags.append(f"experiment-{experiment.experiment_id}")
    if experiment.module_configuration_id is not None:
        tags.append(f"module-configuration-{experiment.module_configuration_id}")
    if experiment.run_id is not None:
        tags.append(f"run-{experiment.run_id}")
        
    chat_prompt.tags = tags
    
    if supports_function_calling(model):
        #chain = create_structured_output_chain(pydantic_object, llm=model, prompt=chat_prompt, tags=tags)
        # output = model.invoke("just testing") 
        # return pydantic_object.parse_obj(output)
        openai_functions = [convert_to_openai_function(pydantic_object)]

        runnable = chat_prompt | model.bind(functions=openai_functions).with_retry(
            retry_if_exception_type=(ValueError, OutputParserException),
            wait_exponential_jitter=True,
            stop_after_attempt=3,
        ) | JsonOutputFunctionsParser()
        try:
            #return await chain.arun(**prompt_input)
            #output_dict = runnable.invoke(prompt_input)
            output_dict = await runnable.ainvoke(prompt_input)
            print(output_dict)
            return pydantic_object.parse_obj(output_dict)
        except (OutputParserException, ValidationError):
            # In the future, we should probably have some recovery mechanism here (i.e. fix the output with another prompt)
            return None
    elif is_azure_call(model) :
        output_parser = PydanticOutputParser(pydantic_object=pydantic_object)
        try:    
            runnable = chat_prompt | model.with_retry(
                retry_if_exception_type=(ValueError, OutputParserException),
                wait_exponential_jitter=True,
                stop_after_attempt=3,
            ) | output_parser
            output_dict = await runnable.ainvoke(prompt_input)
            print(output_dict)
            return pydantic_object.parse_obj(output_dict)
        except (OutputParserException, ValidationError):
            # In the future, we should probably have some recovery mechanism here (i.e. fix the output with another prompt)
            return None

    
    output_parser = PydanticOutputParser(pydantic_object=pydantic_object)
    #chain = LLMChain(llm=model, prompt=chat_prompt, output_parser=output_parser, tags=tags)
    
    
    runnable = chat_prompt | model | output_parser

    try:
        print(model.__dict__)
        print("This is only valid for ollama right now, shouldnt show for openai")
        result = chat_prompt.invoke(prompt_input)
        # res = model.invoke(result) # no need
        res = call_ollama("Only reply with the json, do not give any comments at all", result.to_string())
        print(res)
        output = output_parser.invoke(res)
        print(output)
        # res= runnable.invoke({"topic": "Software Engineering"} )
        # pass
        # print(res)
        # print(runnable.__dict__)
        # output_dict = await runnable.ainvoke(prompt_input)
        return pydantic_object.parse_obj(output)
        # print(model.invoke("hello world"))
        # return await chain.arun(**prompt_input)
        # output_dict = runnable.invoke(prompt_input)
        # output = await model.invoke(prompt_input) 
        # return pydantic_object.parse_obj(output)

        # output = model.invoke("tell joke no bike no pun")
        # output = llm.invoke("just testing") 
        # print(output)
        # return output
        # if("llama3:70b" in model.metadata.items()): #type: ignore
        #     pass
        
        # model.ainvoke
        #return model.invoke("Tell me a joke without bikes and without puns")
        
        ## output_dict = await runnable.ainvoke(prompt_input)
        # return pydantic_object.parse_obj(output_dict)
        # return await chain.arun(**prompt_input)
    except (OutputParserException, ValidationError):
        # In the future, we should probably have some recovery mechanism here (i.e. fix the output with another prompt)
        return None