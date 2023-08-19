from typing import List, Optional, Sequence
from pydantic import BaseModel, Field

from langchain.chat_models import ChatOpenAI
from langchain.chains import LLMChain
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.output_parsers import PydanticOutputParser, OutputFixingParser
from langchain.schema.output_parser import OutputParserException
from langchain.chains.openai_functions import create_structured_output_chain

from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger

from module_text_llm.config import BasicApproachConfig
from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, num_tokens_from_string

class FeedbackModel(BaseModel):
    title: str = Field(..., description="Very short title, i.e. feedback category", example="Logic Error")
    description: str = Field(..., description="Feedback description")
    line_start: Optional[int] = Field(..., description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(..., description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")

    class Config:
        title = "Feedback"


class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: Sequence[FeedbackModel] = Field(..., description="Assessment feedbacks")

    class Config:
        title = "Assessment"


def check_token_length_and_omit_from_input_if_necessary(prompt: ChatPromptTemplate, prompt_input, max_input_tokens: int, debug: bool):
    if num_tokens_from_string(prompt.format(**prompt_input)) <= max_input_tokens:
        return prompt_input, True

    omitted_features = []        

    # Input is too long -> Try to omit example_solution
    if "example_solution" in prompt_input:
        prompt_input["example_solution"] = "omitted"
        omitted_features.append("example_solution")
        if num_tokens_from_string(prompt.format(**prompt_input)) <= max_input_tokens:
            if debug:
                emit_meta("omitted_features", omitted_features)
            return prompt_input, True
        
    # Input is still too long -> Try to omit problem_statement
    if "problem_statement" in prompt_input:
        prompt_input["problem_statement"] = "omitted"
        omitted_features.append("problem_statement")
        if num_tokens_from_string(prompt.format(**prompt_input)) <= max_input_tokens:
            if debug:
                emit_meta("omitted_features", omitted_features)
            return prompt_input, True

    # Input is still too long -> Model should not run 
    return prompt_input, False


# pylint: disable-msg=too-many-locals
async def suggest_feedback_basic(exercise: Exercise, submission: Submission, config: BasicApproachConfig, debug: bool) -> List[Feedback]:
    model = config.model.get_model()

    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": exercise.grading_instructions,
        "problem_statement": exercise.problem_statement,
        "example_solution": exercise.example_solution,
        "submission": add_sentence_numbers(submission.text)
    }

    supports_function_calling = isinstance(model, ChatOpenAI)

    # Output parser for non-function-calling models
    output_parser = OutputFixingParser.from_llm(parser=PydanticOutputParser(pydantic_object=AssessmentModel), llm=model)
    
    # Prepare prompt
    if supports_function_calling:
        system_message_prompt = SystemMessagePromptTemplate.from_template(config.prompt.system_message)
        human_message_prompt = HumanMessagePromptTemplate.from_template(config.prompt.human_message)
    else:
        system_message_prompt = SystemMessagePromptTemplate.from_template(config.prompt.system_message + "\n{format_instructions}")
        system_message_prompt.prompt.partial_variables = {"format_instructions": output_parser.get_format_instructions()}
        system_message_prompt.prompt.input_variables.remove("format_instructions")
        human_message_prompt = HumanMessagePromptTemplate.from_template(config.prompt.human_message + "\nJSON Response:")
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

    prompt_input, should_run = check_token_length_and_omit_from_input_if_necessary(chat_prompt, prompt_input, config.max_input_tokens, debug)
    if not should_run:
        logger.warning("Input too long. Skipping.")
        if debug:
            emit_meta("prompt", chat_prompt.format(**prompt_input))
            emit_meta("error", "Input too long. Skipping.")
        
        # Return early since we cannot run the model
        return []

    if supports_function_calling:        
        chain = create_structured_output_chain(AssessmentModel, llm=model, prompt=chat_prompt)
        result = chain.run(**prompt_input)
    else:
        chain = LLMChain(llm=model, prompt=chat_prompt)
        output = chain.run(**prompt_input)

        try:
            result = output_parser.parse(output)
        except OutputParserException as e:
            logger.warning("Could not parse and fix output: %s", e)
            result = AssessmentModel(feedbacks=[])
            if debug:
                emit_meta("parsing_error", output)

    if debug:
        emit_meta("prompt", chat_prompt.format(**prompt_input))

    feedbacks = []
    for feedback in result.feedbacks:
        index_start, index_end = get_index_range_from_line_range(feedback.line_start, feedback.line_end, submission.text)
        feedbacks.append(Feedback(
            id=None,
            grading_instruction_id=None,
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback.title,
            description=feedback.description,
            index_start=index_start,
            index_end=index_end,
            credits=feedback.credits,
            meta={}
        ))

    return feedbacks