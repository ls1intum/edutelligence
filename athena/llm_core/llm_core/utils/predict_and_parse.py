from typing import Optional, Type, TypeVar, List
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, ValidationError
from langchain_core.runnables import RunnableSequence
from athena import get_experiment_environment
from llm_core.models import DefaultModelConfig

T = TypeVar("T", bound=BaseModel)

async def predict_and_parse(
        model: BaseLanguageModel,
        chat_prompt: ChatPromptTemplate, 
        prompt_input: dict, 
        pydantic_object: Type[T], 
        tags: Optional[List[str]],
        use_function_calling: bool = False

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
    experiment = get_experiment_environment()

    tags = tags or []
    if experiment.experiment_id is not None:
        tags.append(f"experiment-{experiment.experiment_id}")
    if experiment.module_configuration_id is not None:
        tags.append(f"module-configuration-{experiment.module_configuration_id}")
    if experiment.run_id is not None:
        tags.append(f"run-{experiment.run_id}")

    
    if (use_function_calling):
        structured_output_llm = model.with_structured_output(pydantic_object)
        chain = chat_prompt | structured_output_llm
        
        try:
            result = await chain.ainvoke(prompt_input, config={"tags": tags})
            
            if isinstance(result, pydantic_object):
                return result
            else:
                raise ValueError("Parsed output does not match the expected Pydantic model.")
            
        except ValidationError as e:
            raise ValueError(f"Could not parse output: {e}") from e
        
    else:
        structured_output_llm = model.with_structured_output(pydantic_object, method = "json_mode")
        chain = RunnableSequence(
            chat_prompt,
            structured_output_llm
        )
        try:
            return await chain.ainvoke(prompt_input, config={"tags": tags})
        except ValidationError as e:
            raise ValueError(f"Could not parse output: {e}") from e
        
