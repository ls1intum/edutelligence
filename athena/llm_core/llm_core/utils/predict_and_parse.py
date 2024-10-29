from typing import Optional, Type, TypeVar, List

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseLanguageModel
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.output_parsers.openai_functions import JsonOutputFunctionsParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, ValidationError
from langchain_core.tracers import langchain
from langchain_core.utils.function_calling import convert_to_openai_function
from athena import get_experiment_environment
from athena.logger import logger
from .llm_utils import supports_function_calling

T = TypeVar("T", bound=BaseModel)

async def predict_and_parse(
        model: BaseLanguageModel,
        chat_prompt: ChatPromptTemplate,
        prompt_input: dict,
        pydantic_object: Type[T],
        tags: Optional[List[str]]
    ) -> Optional[T]:
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
    langchain.debug = True

    experiment = get_experiment_environment()

    tags = tags or []
    if experiment.experiment_id is not None:
        tags.append(f"experiment-{experiment.experiment_id}")
    if experiment.module_configuration_id is not None:
        tags.append(f"module-configuration-{experiment.module_configuration_id}")
    if experiment.run_id is not None:
        tags.append(f"run-{experiment.run_id}")

    if supports_function_calling(model):
        openai_functions = [convert_to_openai_function(pydantic_object)]

        runnable = chat_prompt | model.bind(functions=openai_functions).with_retry(
            retry_if_exception_type=(ValueError, OutputParserException),
            wait_exponential_jitter=True,
            stop_after_attempt=3,
        ) | JsonOutputFunctionsParser()

        try:
            output_dict = await runnable.ainvoke(prompt_input)
            return pydantic_object.parse_obj(output_dict)
        except (OutputParserException, ValidationError) as e:
            logger.error("Exception type: %s, Message: %s", type(e).__name__, e)
            return None

    output_parser = PydanticOutputParser(pydantic_object=pydantic_object)

    runnable = chat_prompt | model.with_retry(
        retry_if_exception_type=(ValueError, OutputParserException),
        wait_exponential_jitter=True,
        stop_after_attempt=3,
    ) | output_parser

    try:
        output_dict = await runnable.ainvoke(prompt_input)
        return pydantic_object.parse_obj(output_dict)
    except (OutputParserException, ValidationError) as e:
        logger.error("Exception type: %s, Message: %s", type(e).__name__, e)
        return None