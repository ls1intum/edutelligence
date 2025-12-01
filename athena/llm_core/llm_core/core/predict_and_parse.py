from typing import Optional, Type, TypeVar, List, Union
from langchain_core.language_models import BaseLanguageModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableSequence, RunnableLambda
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, ValidationError
from athena import get_experiment_environment
from llm_core.utils.append_format_instructions import append_format_instructions
from llm_core.utils.llm_utils import remove_system_message
from llm_core.models.model_config import ModelConfig
from langchain_core.messages import AIMessage, BaseMessage

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
        structured_output_llm = llm_model.with_structured_output(pydantic_object, method="json_mode")
    elif model.supports_function_calling():
        structured_output_llm = llm_model.with_structured_output(pydantic_object)
    else:
        # Many non-OpenAI endpoints (e.g., LM Studio) may prepend metadata tokens
        # or wrap JSON in code fences. Clean the model text before JSON parsing.
        def _extract_json_text(x: Union[str, BaseMessage]) -> str:
            # Get raw text
            if isinstance(x, (AIMessage, BaseMessage)):
                text = getattr(x, "content", "") or ""
            else:
                text = str(x)

            # Remove common leading control tokens (LM Studio, etc.)
            # Example: "<|channel|>final <|constrain|>JSON<|message|>{...}"
            # Strategy: find the first '{' or '[' and return the balanced JSON substring.
            start_candidates = []
            lbrace = text.find("{")
            if lbrace != -1:
                start_candidates.append(lbrace)
            lbrack = text.find("[")
            if lbrack != -1:
                start_candidates.append(lbrack)

            if not start_candidates:
                return text.strip()

            start = min(start_candidates)
            # Balanced scan for object/array
            open_char = text[start]
            close_char = '}' if open_char == '{' else ']'
            depth = 0
            in_string = False
            escape = False
            for i in range(start, len(text)):
                ch = text[i]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == '\\':
                        escape = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == open_char:
                        depth += 1
                    elif ch == close_char:
                        depth -= 1
                        if depth == 0:
                            return text[start: i + 1].strip()

            # Fallback: return from start to end if balancing failed
            return text[start:].strip()

        structured_output_llm = RunnableSequence(
            llm_model,
            RunnableLambda(_extract_json_text),
            PydanticOutputParser(pydantic_object=pydantic_object),
        )

    chain = RunnableSequence(chat_prompt, structured_output_llm)

    try:
        return await chain.ainvoke(prompt_input, config={"tags": tags}, debug=True)
    except ValidationError as e:
        raise ValueError(f"Could not parse output: {e}") from e

