from typing import List, Tuple, Optional

import tiktoken
from nltk.tokenize import sent_tokenize

# This is correct for gpt-4 and chat gpt3.5 but might be different for other models
def num_tokens_from_string(string: str) -> int:
    """Returns the number of tokens in a text string."""
    encoding = tiktoken.get_encoding("cl100k_base")
    num_tokens = len(encoding.encode(string))
    return num_tokens


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
    line_start_index = min(max(int(line_start), 0), len(sentence_spans) - 1)

    line_end_index = min(max(int(line_end), 0), len(sentence_spans) - 1)
    
    return sentence_spans[line_start_index][0], sentence_spans[line_end_index][1]
