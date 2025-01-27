from typing import Type, TypeVar, List
from pydantic import BaseModel
import tiktoken
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain.base_language import BaseLanguageModel
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.output_parsers import PydanticOutputParser
from athena import emit_meta

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
    return isinstance(model, ChatOpenAI)  or isinstance(model, AzureChatOpenAI)


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
    system_message_prompt.prompt.partial_variables = {"format_instructions": output_parser.get_format_instructions()}
    system_message_prompt.prompt.input_variables.remove("format_instructions")
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_message + "\n\nJSON response following the provided schema: ")
    return ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

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
    system_message_prompt.prompt.partial_variables = {"format_instructions": output_parser.get_format_instructions()}
    system_message_prompt.prompt.input_variables.remove("format_instructions")
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_message + "\n\nJSON response following the provided schema: ")
    return ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

def get_chat_prompt_with_formatting_instructions_2(
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

    human_message_prompt = HumanMessagePromptTemplate.from_template(human_message + "\n\nJSON response following the provided schema: ")
    output_parser = PydanticOutputParser(pydantic_object=pydantic_object)
    human_message_prompt = SystemMessagePromptTemplate.from_template(human_message + "\n{format_instructions}")
    human_message_prompt.prompt.partial_variables = {"format_instructions": output_parser.get_format_instructions()}
    human_message_prompt.prompt.input_variables.remove("format_instructions")
    system_message_prompt = HumanMessagePromptTemplate.from_template(system_message + "\n\n Your response must be in JSON, containing the field of an instruction")
    return ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

def get_human_format_instructions_assessment_model():
    format_instructions = """
    
    """
    return format_instructions
def get_human_format_instructions_feedback_model():
    format_instructions = """
    
    """
    return format_instructions

def get_simple_chat_prompt(
        system_message: str, 
        human_message: str,
        ) -> ChatPromptTemplate:
        system_message_prompt = SystemMessagePromptTemplate.from_template(system_message)
        human_message_prompt = HumanMessagePromptTemplate.from_template(human_message)
        return ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])