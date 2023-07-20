import json
from typing import List

from langchain.chains import LLMChain
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

from athena.programming import Exercise, Submission, Feedback
from athena.logger import logger

from module_programming_llm.helpers.utils import get_diff, get_file_extension, load_files_from_repo, add_line_numbers
from module_programming_llm.helpers.models import chat

from .prompts.basic_feedback_provider import system_template, human_template

async def suggest_feedback(exercise: Exercise, submission: Submission) -> List[Feedback]:
    max_prompt_length = 2560
    input_list: List[dict] = []

    if exercise.meta['file_grading_instructions'] is None:
        raise ValueError("No file grading instructions found for exercise in meta.")
    if exercise.meta['file_problem_statements'] is None:
        raise ValueError("No file problem statements found for exercise in meta.")

    # Feature extraction
    solution_repo = exercise.get_solution_repository()
    template_repo = exercise.get_template_repository()
    submission_repo = submission.get_repository()
    
    file_extension = get_file_extension(exercise.programming_language)
    if file_extension is None:
        raise ValueError(f"Could not determine file extension for programming language {exercise.programming_language}.")

    for file_path, submission_content in load_files_from_repo(submission_repo, file_filter=lambda x: x.endswith(file_extension) if file_extension else False).items():
        if submission_content is None:
            continue
            
        problem_statement = exercise.meta['file_problem_statements'].get(file_path)
        if problem_statement is None:
            logger.info("No problem statement for %s, skipping.", file_path)
            continue

        grading_instructions = exercise.meta['file_grading_instructions'].get(file_path)
        if grading_instructions is None:
            logger.info("No grading instructions for %s, skipping.", file_path)
            continue

        submission_content = add_line_numbers(submission_content)
        solution_to_submission_diff = get_diff(src_repo=solution_repo, dst_repo=submission_repo, src_prefix="solution", dst_prefix="submission", file_path=file_path)
        template_to_submission_diff = get_diff(src_repo=template_repo, dst_repo=submission_repo, src_prefix="template", dst_prefix="submission", file_path=file_path)

        input_list.append({
            "file_path": file_path,
            "submission_content": submission_content,
            "solution_to_submission_diff": solution_to_submission_diff,
            "template_to_submission_diff": template_to_submission_diff,
            "grading_instructions": grading_instructions,
            "problem_statement": problem_statement,
        })
    
    system_message_prompt = SystemMessagePromptTemplate.from_template(system_template)
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

    # Filter long prompts
    input_list = [input for input in input_list if chat.get_num_tokens_from_messages(chat_prompt.format_messages(**input)) <= max_prompt_length]

    # Completion
    chain = LLMChain(llm=chat, prompt=chat_prompt)
    if not input_list:
        return []
    result = await chain.agenerate(input_list)
    
    # Parse result
    feedback_proposals: List[Feedback] = []
    for input, generations in zip(input_list, result.generations):
        file_path = input["file_path"]
        for generation in generations:
            try:
                feedbacks = json.loads(generation.text)
            except json.JSONDecodeError:
                logger.error("Failed to parse feedback json: %s", generation.text)
                continue
            if not isinstance(feedbacks, list):
                logger.error("Feedback json is not a list: %s", generation.text)
                continue

            for feedback in feedbacks:
                line = feedback.get("line", None)
                detail_text = feedback.get("text", "")
                credits = feedback.get("credits", 0.0)
                feedback_proposals.append(
                    Feedback(
                        exercise_id=exercise.id,
                        submission_id=submission.id,
                        title=detail_text,
                        description=detail_text,
                        file_path=file_path,
                        line_start=line,
                        credits=credits,
                        meta={},
                    )
                )

    return feedback_proposals