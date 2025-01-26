from typing import Optional, Type, TypeVar, List
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, ValidationError
from langchain_core.runnables import RunnableSequence
from athena import get_experiment_environment
from langchain_community.chat_models import ChatOllama # type: ignore
from langchain.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI

T = TypeVar("T", bound=BaseModel)

def isOllama(model: BaseLanguageModel) -> bool:
    return isinstance(model, ChatOllama)

async def predict_plain_text(        
        model: BaseLanguageModel, 
        chat_prompt: ChatPromptTemplate, 
        prompt_input: dict,
        tags: Optional[List[str]]) -> Optional[str]: 
    """Predict plain text using the provided model and prompt.

    Args:
        model (BaseLanguageModel): The model to predict with.
        chat_prompt (ChatPromptTemplate): The prompt template to use.
        prompt_input (dict): Input parameters to use for the prompt.
        tags (Optional[List[str]]): List of tags to tag the prediction with.

    Returns:
        Optional[str]: Prediction as a string, or None if it failed.
    """
    try:
        chain = chat_prompt | model
        return await chain.ainvoke(prompt_input, config={"tags": tags})
    except:
        raise ValueError("Llm prediction failed.")
        
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

    if isOllama(model):
        try:
            outputParser = PydanticOutputParser(pydantic_object = pydantic_object)
            chain = chat_prompt | model
            llm_output = await chain.ainvoke(prompt_input, config={"tags": tags})
            try:
                result = outputParser.parse(llm_output.content)
                return result
            except:
                outputModel = ChatOpenAI(model="gpt-4o-mini")
                structured_output_llm = outputModel.with_structured_output(pydantic_object, method = "json_mode")
                chat_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", """
                 A previous LLM was tasked with creating an assessment, however its not as good as you at creating structured output.
                 This were the prompt inputs {inputs}.
                 Your only task is to format the following output into json. Line_start and Line_end are only integer or None, A grading_instruction_id can be None if not specified."""),
                ("human", "Try to only use information from this output, however if neccessary make your own fixes so that the output is in the desired format but still correct:{output}"),
            ])
                chain = RunnableSequence(
                    chat_prompt,
                    structured_output_llm
                )
                return await chain.ainvoke(input = {"inputs":prompt_input,"output": llm_output.content}, config={"tags": tags})
        except ValidationError as e:
            raise ValueError(f"Could not parse output: {e}") from e
        
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
    