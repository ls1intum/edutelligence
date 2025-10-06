from typing import Optional, Type, TypeVar, List
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableSequence
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, ValidationError
from athena import get_experiment_environment
from llm_core.utils.append_format_instructions import append_format_instructions
from llm_core.utils.llm_utils import remove_system_message
from llm_core.models.model_config import ModelConfig

T = TypeVar("T", bound=BaseModel)

async def predict_and_parse(
        model: ModelConfig, 
        chat_prompt: ChatPromptTemplate, 
        prompt_input: dict, 
        pydantic_object: Type[T], 
        tags: Optional[List[str]],
    ) -> Optional[T]:
    """
    Predicts an LLM completion using the model and parses the output using the provided Pydantic model
    """

    # Remove system messages if the model does not support them
    if not model.supports_system_messages():
        chat_prompt = remove_system_message(chat_prompt)

    llm_model = model.get_model()

    # Add tags
    experiment = get_experiment_environment()
    tags = tags or []
    if experiment.experiment_id is not None:
        tags.append(f"experiment-{experiment.experiment_id}")
    if experiment.module_configuration_id is not None:
        tags.append(f"module-configuration-{experiment.module_configuration_id}")
    if experiment.run_id is not None:
        tags.append(f"run-{experiment.run_id}")

    # Currently structured output and function calling both expect the expected json to be in the prompt input
    chat_prompt = append_format_instructions(chat_prompt, pydantic_object)

    # Run the model and parse the output
    if model.supports_structured_output():
        structured_output_llm = llm_model.with_structured_output(pydantic_object, method = "json_mode")
    elif model.supports_function_calling():
        structured_output_llm = llm_model.with_structured_output(pydantic_object)
    else:
        structured_output_llm = RunnableSequence(llm_model, PydanticOutputParser(pydantic_object=pydantic_object))
    
    chain = RunnableSequence(chat_prompt, structured_output_llm)

    try:
        return await chain.ainvoke(prompt_input, config={"tags": tags}, debug=True)
    except ValidationError as e:
        raise ValueError(f"Could not parse output: {e}") from e
        
