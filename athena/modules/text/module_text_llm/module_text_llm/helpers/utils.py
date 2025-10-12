from typing import List, Tuple, Optional

import tiktoken
from nltk.tokenize import sent_tokenize

from athena import GradingCriterion

# This is correct for gpt-4 and chat gpt3.5 but might be different for other models
def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens


def format_grading_instructions(grading_instructions: Optional[str], grading_criteria: Optional[List[GradingCriterion]]) -> Optional[str]:
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


def add_sentence_numbers(content: str) -> str:
    sentences = sent_tokenize(content)
    sentences = [line for sentence in sentences for line in sentence.split("\n")]
    sentence_numbers_max_length = len(str(len(sentences)))
    return "\n".join(
        f"{str(sentence_number).rjust(sentence_numbers_max_length)}: {sentence}" 
        for sentence_number, sentence 
        in enumerate(sentences)
    )


def get_sentence_spans(content: str) -> List[Tuple[int, int]]:
    sentences = sent_tokenize(content)
    sentences = [line for sentence in sentences for line in sentence.split("\n")]
    sentence_spans = []
    
    remaining_content = content
    current_index = 0
    for sentence in sentences:
        sentence_start_index = remaining_content.index(sentence)
        sentence_end_index = sentence_start_index + len(sentence)
        sentence_spans.append((current_index + sentence_start_index, current_index + sentence_end_index))
        
        remaining_content = remaining_content[sentence_end_index:]
        current_index += sentence_end_index

    return sentence_spans


def get_index_range_from_line_range(line_start: Optional[int], line_end: Optional[int], content: str) -> Tuple[Optional[int], Optional[int]]:
    if line_start is None and line_end is None:
        return None, None
    
    line_start = line_start or line_end or 0
    line_end = line_end or line_start or 0

    if line_start > line_end:
        line_start, line_end = line_end, line_start

    sentence_spans = get_sentence_spans(content)
    
    # Handle empty content case
    if not sentence_spans:
        return None, None
    
    line_start_index = min(max(int(line_start), 0), len(sentence_spans) - 1)

    line_end_index = min(max(int(line_end), 0), len(sentence_spans) - 1)
    
    return sentence_spans[line_start_index][0], sentence_spans[line_end_index][1]


def get_line_range_from_index_range(index_start: Optional[int], index_end: Optional[int], content: str) -> Tuple[Optional[int], Optional[int]]:
    if index_start is None and index_end is None:
        return None, None

    index_start = index_start or index_end or 0
    index_end = index_end or index_start or 0

    if index_start > index_end:
        index_start, index_end = index_end, index_start

    sentence_spans = get_sentence_spans(content)

    line_start = None
    line_end = None

    for line_number, (start_index, end_index) in enumerate(sentence_spans, start=1):
        if start_index <= index_start < end_index:
            line_start = line_number
        if start_index <= index_end <= end_index:
            line_end = line_number
            break
    
    return line_start, line_end