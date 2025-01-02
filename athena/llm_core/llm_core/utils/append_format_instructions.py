from typing import Type, TypeVar
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

def append_format_instructions(
    chat_prompt: ChatPromptTemplate,
    pydantic_object: Type[T]
) -> ChatPromptTemplate:
    """
    Appends format instructions to the first message of an existing chat prompt
    """
    output_parser = PydanticOutputParser(pydantic_object=pydantic_object)
    format_instructions = output_parser.get_format_instructions()

    messages = chat_prompt.messages
    if not messages:
        raise ValueError("Cannot append format instructions to an empty chat prompt")

    # Append format instructions to the first message
    first_message = messages[0]
    if isinstance(first_message, SystemMessagePromptTemplate):
        new_first_message = SystemMessagePromptTemplate.from_template(
            first_message.prompt.template + "<OutputFormat>\n\n{format_instructions}" # type: ignore[attr-defined]
        )
    elif isinstance(first_message, HumanMessagePromptTemplate):
        new_first_message = HumanMessagePromptTemplate.from_template(
            first_message.prompt.template + "<OutputFormat>\n\n{format_instructions}" # type: ignore[attr-defined]
        )
    else:
        raise ValueError(f"Unsupported message type for appending format instructions: {type(first_message)}")
    
    new_first_message.prompt.partial_variables = {"format_instructions": format_instructions} # type: ignore[attr-defined]
    new_first_message.prompt.input_variables.remove("format_instructions") # type: ignore[attr-defined]
    
    return ChatPromptTemplate.from_messages([new_first_message] + messages[1:])
