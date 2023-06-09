import re
from typing import List, Tuple, Optional

from nltk.tokenize import sent_tokenize

from athena.logger import logger


def add_sentence_numbers(content: str) -> str:
    sentences = sent_tokenize(content)
    sentences = [line for sentence in sentences for line in sentence.split("\n")]
    sentence_numbers_max_length = len(str(len(sentences)))
    return "\n".join(
        f"{str(sentence_number).rjust(sentence_numbers_max_length)}: {sentence}" 
        for sentence_number, sentence 
        in enumerate(sentences, start=1)
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


def parse_line_number_reference_as_span(reference: str, content: str) -> Optional[str]:
    start_line_number = None
    end_line_number = None

    # Check if line number range
    if "-" in reference:
        # Get line numbers with regex
        line_number_regex = r"(\d+)-(\d+)"
        line_number_match = re.match(line_number_regex, reference)
        if line_number_match:
            start_line_number, end_line_number = line_number_match.groups()
    else:
        # Get single line number with regex
        line_number_regex = r"(\d+)"
        line_number_match = re.match(line_number_regex, reference)
        if line_number_match:
            start_line_number = end_line_number = line_number_match.groups()[0]

    if start_line_number is None or end_line_number is None:
        logger.warning("Could not parse line number from reference %s", reference)
        return None
    
    sentence_spans = get_sentence_spans(content)
    start_line_index = int(start_line_number) - 1
    end_line_index = int(end_line_number) - 1

    if len(sentence_spans) <= start_line_index or len(sentence_spans) <= end_line_index:
        logger.warning("Line number out of range for reference %s", reference)
        return None
    
    span_start_index, span_end_index = sentence_spans[start_line_index][0], sentence_spans[end_line_index][1]
    return f"{span_start_index}-{span_end_index}"
