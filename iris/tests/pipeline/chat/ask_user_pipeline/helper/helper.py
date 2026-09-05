import datetime
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Counter, Sequence

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from iris.common.pyris_message import IrisMessageRole, PyrisAIMessage, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.llm import CompletionArguments, LlmRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from tests.pipeline.chat.ask_user_pipeline.helper.test_data import FIRST_MESSAGE_TIME

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Helper function to get a pass ratio for a number of pipeline results and a given criteria
def get_pass_ratio(tested_items: Sequence, check_fn: Callable[[str], bool]) -> float:
    assert len(tested_items) > 0, "tested_items must not be empty"

    passed = sum(1 for item in tested_items if check_fn(item))
    return passed / len(tested_items)


@dataclass
class JudgeVote:
    ok: bool
    reason: str
    raw: str


# Runs the judge model `instances` times on a single artifact (a question, or
# a pair of questions joined into one message) and returns one vote per
# instance, each carrying the judge's short justification. This is the
# building block for llm_majority_vote
def _run_llm_judge(
    evaluation_prompt: str,
    instances: int,
    output_to_evaluate: str,
    task: str,
    template: str,
    code: str,
) -> list[JudgeVote]:
    # Separate LLM-as-a-judge model used by tests that grade
    # another LLM's output (e.g. tests/pipeline/chat/ask_user_pipeline/helper/helper.py::llm_evaluate)
    # which are using GPT models.
    # LLM-as-a-judge carries systematic biases -- among them self-enhancement
    # bias: models have been shown to favor their own generations. That is
    # why it is recommended to use a different model for judging pipeline output.
    completion_args = CompletionArguments(max_tokens=2000)
    llm = IrisLangchainChatModel(
        request_handler=LlmRequestHandler(model_id="gemini-3.1-pro"),
        completion_args=completion_args,
    )

    rendered_prompt = Template(evaluation_prompt).render(
        task=task, template=template, code=code
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=rendered_prompt),
            HumanMessage(content=output_to_evaluate),
        ]
    )

    votes = []

    for i in range(instances):
        response = (prompt | llm | StrOutputParser()).invoke({})
        logger.info(f"LLM evaluation instance {i}: response: {response}")

        stripped = response.strip()
        if stripped.startswith("!ok!"):
            votes.append(
                JudgeVote(ok=True, reason=stripped[len("!ok!") :].strip(), raw=response)
            )
        elif stripped.startswith("!bad!"):
            votes.append(
                JudgeVote(
                    ok=False, reason=stripped[len("!bad!") :].strip(), raw=response
                )
            )
        else:
            logger.error(f"Evaluation result of instance {i} is invalid!")
            votes.append(
                JudgeVote(
                    ok=False, reason=f"invalid judge response: {response!r}", raw=response
                )
            )

    return votes


# Runs the judge model `instances` times and returns the majority pass/fail
# together with the concatenated reasons of all votes matching that majority
def llm_majority_vote(
    evaluation_prompt: str,
    instances: int,
    output_to_evaluate: str,
    task: str,
    template: str,
    code: str,
) -> tuple[bool, str]:
    votes = _run_llm_judge(
        evaluation_prompt, instances, output_to_evaluate, task, template, code
    )
    ok_count = sum(1 for v in votes if v.ok)
    majority = ok_count > instances / 2
    reason = " | ".join(v.reason for v in votes if v.ok == majority)
    return majority, reason


# Helper function to convert string into PyrisMessage object sent by USER
def to_user_message(message: str):
    return PyrisMessage(
        sender=IrisMessageRole.USER,
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[TextMessageContentDTO(textContent=message)],
    )


# Helper function to convert string into PyrisMessage object sent by AI
def to_ai_message(message: str):
    return PyrisAIMessage(
        sentAt=datetime.datetime(2026, 1, 10),
        contents=[TextMessageContentDTO(textContent=message)],
        toolCalls=[],
    )


def get_pyris_message(message_number: int, from_user: bool, content: str):
    return PyrisMessage(
        id=message_number,
        sender=IrisMessageRole.USER if from_user else IrisMessageRole.ASSISTANT,
        sentAt=FIRST_MESSAGE_TIME + timedelta(minutes=message_number),
        contents=[TextMessageContentDTO(textContent=content)],
    )
