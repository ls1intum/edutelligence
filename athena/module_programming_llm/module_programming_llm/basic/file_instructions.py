import json

from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)

from athena.programming import Exercise
from athena.logger import logger

from module_programming_llm.helpers.utils import get_diff, get_file_extension
from module_programming_llm.helpers.models import chat

from .prompts.generate_file_grading_instructions import system_template as system_template_grading_instructions, human_template as human_template_grading_instructions
from .prompts.generate_file_problem_statements import system_template as system_template_problem_statements, human_template as human_template_problem_statements

def generate_file_grading_instructions(exercise: Exercise):
    grading_instructions = exercise.grading_instructions

    solution_repo = exercise.get_solution_repository()
    template_repo = exercise.get_template_repository()
    file_extension = get_file_extension(exercise.programming_language) or ""
    changed_files = get_diff(src_repo=template_repo, dst_repo=solution_repo, file_path=f"*{file_extension}", name_only=True)
    

    
    system_message_prompt = SystemMessagePromptTemplate.from_template(system_template_grading_instructions)
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_template_grading_instructions)
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

    result = chat(chat_prompt.format_prompt(grading_instructions=grading_instructions, changed_files=changed_files).to_messages())
    
    try:
        return json.loads(result.content)
    except json.JSONDecodeError:
        logger.error("Could not decode JSON response from chat: %s", result.content)
    return None


def generate_file_problem_statements(exercise: Exercise):
    problem_statement = exercise.problem_statement

    solution_repo = exercise.get_solution_repository()
    template_repo = exercise.get_template_repository()
    file_extension = get_file_extension(exercise.programming_language) or ""
    changed_files = get_diff(src_repo=template_repo, dst_repo=solution_repo, file_path=f"*{file_extension}", name_only=True)

    system_message_prompt = SystemMessagePromptTemplate.from_template(system_template_problem_statements)
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_template_problem_statements)
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt, human_message_prompt])

    result = chat(chat_prompt.format_prompt(problem_statement=problem_statement, changed_files=changed_files).to_messages())
    
    try:
        return json.loads(result.content)
    except json.JSONDecodeError:
        logger.error("Could not decode JSON response from chat: %s", result.content)
    return None