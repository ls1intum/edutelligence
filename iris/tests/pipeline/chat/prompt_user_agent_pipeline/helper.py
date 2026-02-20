import logging
import datetime
from typing import Sequence, Callable, Counter
import re
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from jinja2 import Template

from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# Helper function to extract keywords from code input, that are less often used in exercise template
def extract_keywords(task_template: str, code: str, top_n: int = 10):
    """
    Extract keywords that represent the conceptual difference between task and code.
    This focuses on tokens that appear significantly more often in the code than in the task text.
    """
    # Normalize text
    task_text = task_template.lower()
    code_text = code.lower()


    # Tokenization (simple words and identifiers)
    token_pattern = r"[a-zA-Z_][a-zA-Z0-9_]*"


    task_tokens = re.findall(token_pattern, task_text)
    code_tokens = re.findall(token_pattern, code_text)


    task_counts = Counter(task_tokens)
    code_counts = Counter(code_tokens)


    # Compute difference: code tokens that are more characteristic in code
    diff_scores = {}
    for token, count in code_counts.items():
        task_count = task_counts.get(token, 0)
        # Only consider tokens that appear more often in code
        if count > task_count:
            diff_scores[token] = count - task_count


    # Select most relevant tokens
    keywords = [token for token, _ in Counter(diff_scores).most_common(top_n)]


    return keywords

# Helper function to get a pass ratio for a number of pipeline results and a given criteria
def get_pass_ratio(
        tested_items: Sequence,
        check_fn: Callable[[str], bool]
) -> float:
    assert len(tested_items) > 0, "tested_items must not be empty"

    passed = sum(1 for item in tested_items if check_fn(item))
    return passed / len(tested_items)



# Evaluates given pipeline output using a given evaluation prompt and exercise context, acceptance ratio is returned
def llm_evaluate(evaluation_prompt: str, instances: int, output_to_evaluate: str, task: str, template: str, code: str):
    # Create LLM for evaluation
    completion_args = CompletionArguments(temperature=0.6, max_tokens=2000)
    llm = IrisLangchainChatModel(
        request_handler=ModelVersionRequestHandler(version="gpt-4.1-mini"),
        completion_args=completion_args
    )

    rendered_prompt = Template(evaluation_prompt).render(
        task=task,
        template=template,
        code=code
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=rendered_prompt),
            HumanMessage(content=output_to_evaluate),
        ]
    )

    ok = 0

    for i in range(instances):
        response = (prompt | llm | StrOutputParser()).invoke({})
        logger.info(f"LLM evaluation instance {i}: response: {response}")
        if "!ok!" in response:
            ok += 1
        elif not "!bad!" in response:
            logger.error(f"Evaluation result of instance {i} is invalid!")

    verdict = ok / instances

    logger.info(f"Verdict is {verdict}")

    return verdict

from iris.common.pyris_message import PyrisMessage, IrisMessageRole, PyrisAIMessage

# Helper function to convert string into PyrisMessage object sent by USER
def to_user_message(message: str):
    return PyrisMessage(
        sender=IrisMessageRole.USER,
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[
            TextMessageContentDTO(textContent=message)
        ]
    )

# Helper function to convert string into PyrisMessage object sent by AI
def to_ai_message(message: str):
    return PyrisAIMessage(
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[
            TextMessageContentDTO(textContent=message)
        ],
        toolCalls=None
    )