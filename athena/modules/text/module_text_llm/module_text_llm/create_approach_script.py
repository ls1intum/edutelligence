"""
This script creates a new approach inside the module_text_llm package.

Run with: python create_approach_script.py <approach_name>

It creates the __init__.py, prompt_generate_suggestions.py, and generate_suggestions.py files for the new approach.

It also imports the new approach into the config.py and adds the new approach to the ApproachConfigUnion.
"""
import re
import argparse
from pathlib import Path

def to_camel_case(snake_str: str) -> str:
    components = snake_str.split('_')
    return ''.join(x.title() for x in components)


def create_approach_directory(approach_name: str) -> Path:
    base_dir = Path(__file__).parent / approach_name
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def create_init_py(base_dir: Path, approach_name: str) -> None:
    init_content = f"""
from module_text_llm.approach_config import ApproachConfig
from pydantic import Field
from typing import Literal
from athena.text import Exercise, Submission
from module_text_llm.{approach_name}.generate_suggestions import generate_suggestions
from module_text_llm.{approach_name}.prompt_generate_suggestions import GenerateSuggestionsPrompt

class {to_camel_case(approach_name)}Config(ApproachConfig):
    type: Literal['{approach_name.lower()}'] = '{approach_name.lower()}'
    generate_suggestions_prompt: GenerateSuggestionsPrompt = Field(default=GenerateSuggestionsPrompt())
    
    async def generate_suggestions(self, exercise: Exercise, submission: Submission, config, debug: bool):
        return await generate_suggestions(exercise, submission, config, debug)
"""
    with open(base_dir / "__init__.py", "w", encoding="utf-8") as f:
        f.write(init_content.strip())


def create_prompt_py(base_dir: Path) -> None:
    prompt_content = '''
from pydantic import Field, BaseModel
from typing import List, Optional

system_message = """\
You are an AI tutor for text assessment at a prestigious university.

# Task
Create graded feedback suggestions for a student's text submission that a human tutor would accept. \
Meaning, the feedback you provide should be applicable to the submission with little to no modification.

# Style
1. Constructive, 2. Specific, 3. Balanced, 4. Clear and Concise, 5. Actionable, 6. Educational, 7. Contextual

# Problem statement
{problem_statement}

# Example solution
{example_solution}

# Grading instructions
{grading_instructions}
Max points: {max_points}, bonus points: {bonus_points}
    
Respond in json.
"""

human_message = """\
Student's submission to grade (with sentence numbers <number>: <sentence>):

{submission}
"""

# Input Prompt
class GenerateSuggestionsPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")

# Output Object
class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")
'''
    with open(base_dir / "prompt_generate_suggestions.py", "w", encoding="utf-8") as f:
        f.write(prompt_content.strip())


def create_generate_suggestions_py(base_dir: Path) -> None:
    generate_suggestions_content = """
# Placeholder for generate suggestions logic.
def generate_suggestions():
    pass
"""
    with open(base_dir / "generate_suggestions.py", "w", encoding="utf-8") as f:
        f.write(generate_suggestions_content.strip())


def update_config_py(approach_name: str) -> None:
    config_path = Path(__file__).parent / "config.py"
    camel_case_name = to_camel_case(approach_name)
    config_import = f"from module_text_llm.{approach_name.lower()} import {camel_case_name}Config"

    with open(config_path, "r+", encoding="utf-8") as f:
        content = f.read()

        # Add import
        if config_import not in content:
            content = f"{config_import}\n{content}"

        # Update Union
        union_pattern = r"ApproachConfigUnion = Union\[(.*?)\]"
        match = re.search(union_pattern, content, re.DOTALL)
        if match:
            updated_union = f"{match.group(1).strip()}, {camel_case_name}Config".replace(" ,", ",")
            content = re.sub(union_pattern, f"ApproachConfigUnion = Union[{updated_union}]", content)

        f.seek(0)
        f.write(content)
        f.truncate()


def create_approach(approach_name: str) -> None:
    base_dir = create_approach_directory(approach_name)
    create_init_py(base_dir, approach_name)
    create_prompt_py(base_dir)
    create_generate_suggestions_py(base_dir)
    update_config_py(approach_name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a new approach for the Athena project.")
    parser.add_argument("approach_name", help="The name of the new approach (in snake_case).")
    args = parser.parse_args()
    
    create_approach(args.approach_name)
