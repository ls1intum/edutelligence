from typing import List, TypeVar
from pydantic import BaseModel
import tiktoken
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
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


def check_prompt_length_and_omit_features_if_necessary(
    prompt: ChatPromptTemplate,
    prompt_input: dict,
    max_input_tokens: int,
    omittable_features: List[str],
    debug: bool,
):
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


def get_chat_prompt(
    system_message: str,
    human_message: str,
) -> ChatPromptTemplate:
    system_message_prompt = SystemMessagePromptTemplate.from_template(system_message)
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_message)
    return ChatPromptTemplate.from_messages(
        [system_message_prompt, human_message_prompt]
    )

def remove_system_message(chat_prompt: ChatPromptTemplate) -> ChatPromptTemplate:
    """
    Create a NEW ChatPromptTemplate with "system" messages replaced as "human" if the model does not support system messages.
    """
    new_prompt_templates = []
    for prompt_msg in chat_prompt.messages:
        if isinstance(prompt_msg, SystemMessagePromptTemplate):
            # Convert it to a human prompt, preserving content
            new_prompt_templates.append(
                HumanMessagePromptTemplate.from_template(
                    "[System message]: " + prompt_msg.prompt.template  # type: ignore
                )
            )
        else:
            new_prompt_templates.append(prompt_msg)
    return ChatPromptTemplate.from_messages(new_prompt_templates)
