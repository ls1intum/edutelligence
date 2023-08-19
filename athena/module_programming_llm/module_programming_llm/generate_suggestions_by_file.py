from typing import List, Optional, Sequence

from pydantic import BaseModel, Field
from langchain.chains.openai_functions import create_structured_output_chain

from athena import emit_meta
from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger

from module_programming_llm.config import BasicApproachConfig
from module_programming_llm.split_grading_instructions_by_file import generate_and_store_split_grading_instructions_if_needed
from module_programming_llm.split_problem_statement_by_file import generate_and_store_split_problem_statement_if_needed
from module_programming_llm.helpers.llm_utils import check_prompt_length_and_omit_features_if_necessary, get_chat_prompt_with_formatting_instructions
from module_programming_llm.helpers.utils import get_diff, get_programming_language_file_extension, load_files_from_repo, add_line_numbers


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


# pylint: disable=too-many-locals
async def generate_suggestions_by_file(exercise: Exercise, submission: Submission, config: BasicApproachConfig, debug: bool) -> List[Feedback]:
    model = config.model.get_model()

    # Get split grading instructions
    split_grading_instructions = generate_and_store_split_grading_instructions_if_needed(exercise=exercise, config=config, debug=debug)
    file_grading_instructions = { item.file_name: item.grading_instructions for item in split_grading_instructions.instructions }

    # Get split problem statement
    split_problem_statement = generate_and_store_split_problem_statement_if_needed(exercise=exercise, config=config, debug=debug)
    file_problem_statements = { item.file_name: item.problem_statement for item in split_problem_statement.problem_statements }

    prompt_inputs: List[dict] = []
    
    # Feature extraction
    solution_repo = exercise.get_solution_repository()
    template_repo = exercise.get_template_repository()
    submission_repo = submission.get_repository()
    
    file_extension = get_programming_language_file_extension(exercise.programming_language)
    if file_extension is None:
        raise ValueError(f"Could not determine file extension for programming language {exercise.programming_language}.")

    files = load_files_from_repo(
        submission_repo, 
        file_filter=lambda x: x.endswith(file_extension) if file_extension else False
    )

    for file_path, content in files.items():
        if content is None:
            continue
        
        problem_statement = file_problem_statements.get(file_path, "No relevant problem statement section found.")
        grading_instructions = file_grading_instructions.get(file_path, "No relevant grading instructions found.")

        content = add_line_numbers(content)
        solution_to_submission_diff = get_diff(src_repo=solution_repo, dst_repo=submission_repo, src_prefix="solution", dst_prefix="submission", file_path=file_path)
        template_to_submission_diff = get_diff(src_repo=template_repo, dst_repo=submission_repo, src_prefix="template", dst_prefix="submission", file_path=file_path)

        prompt_inputs.append({
            "file_path": file_path,
            "submission": content,
            "max_points": exercise.max_points,
            "bonus_points": exercise.bonus_points,
            "solution_to_submission_diff": solution_to_submission_diff,
            "template_to_submission_diff": template_to_submission_diff,
            "grading_instructions": grading_instructions,
            "problem_statement": problem_statement,
        })
    
    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=config.generate_suggestions_by_file_prompt.system_message, 
        human_message=config.generate_suggestions_by_file_prompt.human_message, 
        pydantic_object=AssessmentModel
    )

    # Filter long prompts (omitting features if necessary)
    omittable_features = [
        "problem_statement", 
        "grading_instructions",
        "template_to_submission_diff",
        "solution_to_submission_diff"
    ]
    prompt_inputs = [
        omitted_prompt_input for omitted_prompt_input, should_run in
        [check_prompt_length_and_omit_features_if_necessary(
            prompt=chat_prompt,
            prompt_input=prompt_input,
            max_input_tokens=config.max_input_tokens,
            omittable_features=omittable_features,
            debug=debug
        ) for prompt_input in prompt_inputs]
        if should_run
    ]

    chain = create_structured_output_chain(AssessmentModel, llm=model, prompt=chat_prompt)
    if not prompt_inputs:
        return []
    result = await chain.agenerate(prompt_inputs)

    logger.info("Generated result: %s ", result)

    return []
    # return predict_and_parse(
    #     model=model, 
    #     chat_prompt=chat_prompt, 
    #     prompt_input={
    #         "grading_instructions": exercise.grading_instructions, 
    #         "changed_files": changed_files
    #     }, 
    #     pydantic_object=SplitGradingInstructions
    # )





# async def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    
#     # Filter long prompts
#     input_list = [input for input in input_list if chat.get_num_tokens_from_messages(chat_prompt.format_messages(**input)) <= max_prompt_length]

#     # Completion
#     chain = LLMChain(llm=chat, prompt=chat_prompt)
#     if not input_list:
#         return []
#     result = await chain.agenerate(input_list)
    
#     # Parse result
#     feedback_proposals: List[Feedback] = []
#     for input, generations in zip(input_list, result.generations):
#         file_path = input["file_path"]
#         for generation in generations:
#             try:
#                 feedbacks = json.loads(generation.text)
#             except json.JSONDecodeError:
#                 logger.error("Failed to parse feedback json: %s", generation.text)
#                 continue
#             if not isinstance(feedbacks, list):
#                 logger.error("Feedback json is not a list: %s", generation.text)
#                 continue

#             for feedback in feedbacks:
#                 line = feedback.get("line", None)
#                 description = feedback.get("text", None)
#                 credits = feedback.get("credits", 0.0)
#                 feedback_proposals.append(
#                     Feedback(
#                         id=None,
#                         exercise_id=exercise.id,
#                         submission_id=submission.id,
#                         title="Feedback",
#                         description=description,
#                         file_path=file_path,
#                         line_start=line,
#                         line_end=None,
#                         credits=credits,
#                         meta={},
#                     )
#                 )

#     return feedback_proposals