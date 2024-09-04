from typing import List, Optional

import tiktoken

from athena import GradingCriterion


# This is correct for gpt-4 and chat gpt3.5 but might be different for other models
def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens


def format_grading_instructions(grading_instructions: Optional[str],
                                grading_criteria: Optional[List[GradingCriterion]]) -> Optional[str]:
    """Formats grading instructions and the grading criteria with nested structured grading instructions into a single string.

    Args:
        grading_instructions (Optional[str]): Grading instructions
        grading_criteria (Optional[List[GradingCriterion]]): Grading criteria with nested structured grading instructions

    Returns:
        Optional[str]: Formatted grading instructions or None if no grading instructions or grading criteria are provided
    """

    if not grading_instructions and not grading_criteria:
        return None

    result = ""
    if grading_instructions:
        result += grading_instructions + "\n\n"

    if grading_criteria:
        for grading_criterion in grading_criteria:
            result += f'Criterion > "{(grading_criterion.title or "Unnamed criterion")}":\n'
            for grading_instruction in grading_criterion.structured_grading_instructions:
                result += f'  - grading_instruction_id={grading_instruction.id} > "{grading_instruction.feedback}": ('
                if grading_instruction.usage_count > 0:
                    result += f'can be used {grading_instruction.usage_count} times in total'
                else:
                    result += "can be used unlimited times"
                result += f', gives {grading_instruction.credits} credits for "{grading_instruction.grading_scale}" grading scale, '
                result += f'usage description: "{grading_instruction.instruction_description}")\n'
            result += "\n"

    return result.strip()


def get_elements(model: dict) -> list[dict]:
    """
    Helper method to retrieve the elements of a model backwards compatible with Apollon version 2 diagrams
    """

    elements: list | dict = model.get("elements", {})

    if isinstance(elements, list):
        return elements

    return list(elements.values())
