import logging
from typing import Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from pydantic import BaseModel

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO

from ...common.pyris_message import IrisMessageRole, PyrisMessage
from ...domain.chat.ask_user_chat.ask_user_chat_pipeline_execution_dto import (
    AskUserPipelineExecutionDTO,
)
from ...domain.data.text_message_content_dto import TextMessageContentDTO
from ...llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from ...llm.langchain import IrisLangchainChatModel
from ...web.status.status_update import StatusCallback
from ..prompts.assess_user_answer_prompt import (
    assess_user_answer_prompt,
    between_min_max_questions_rules,
    conversation_history_prompt,
    exercise_data_prompt,
    over_equal_max_questions_rules,
    under_min_questions_rules,
)
from ..sub_pipeline import SubPipeline

logger = logging.getLogger(__name__)


def _render_conversation_history(history: List[PyrisMessage]) -> str:
    """Render prior Q&A turns as tagged, inert data instead of native chat
    turns, so a student's answer can never carry the "human message" authority
    that many models give the actual conversational channel (see NOTE ON
    PROMPT INJECTION in assess_user_answer_prompt.py). Only USER/ASSISTANT
    turns with text content are included; anything else (tool calls, system,
    context-switch markers) is not part of the Q&A and is dropped."""
    turns: list[str] = []
    for message in history:
        if not message.contents:
            continue
        content = message.contents[0]
        if not isinstance(content, TextMessageContentDTO):
            continue
        if message.sender == IrisMessageRole.USER:
            turns.append(f"<student_answer>\n{content.text_content}\n</student_answer>")
        elif message.sender == IrisMessageRole.ASSISTANT:
            turns.append(f"<tutor_question>\n{content.text_content}\n</tutor_question>")
    return "\n".join(turns) if turns else "(no prior conversation)"


class AssessUserAnswerPipeline(SubPipeline):
    """Pipeline that assesses a given answer by the student to decide whether it is convincing or not"""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: StatusCallback
    prompt: ChatPromptTemplate
    output_parser: StrOutputParser
    tokens: Optional[TokenUsageDTO]

    def __init__(
        self,
        callback: Optional[StatusCallback] = None,
        model: str = "oai-gpt-5-mini",
    ):
        super().__init__(implementation_id="assess_user_answer_pipeline_reference_impl")
        self.callback = callback
        self.tokens = None

        # Set up the language model
        completion_args = CompletionArguments(
            temperature=0, max_tokens=1024, response_format="text"
        )

        request_handler = LlmRequestHandler(model_id=model)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )

        self.output_parser = StrOutputParser()

        # Create the pipeline
        self.pipeline = self.llm | self.output_parser

    @traceable(name="Assess User Answer Pipeline")
    def __call__(self, dto: AskUserPipelineExecutionDTO) -> str:
        """
        Runs the pipeline
            :return: Assessment result
        """
        logger.info("Running assess user answer pipeline...")

        submission_repository = (
            dto.programming_exercise_submission.repository
            if dto.programming_exercise_submission
            else {}
        ) or {}
        template_repository = (
            dto.programming_exercise.template_repository
            if dto.programming_exercise
            else {}
        ) or {}
        submission_file_list = "\n------------\n".join(
            f"{file_name}:\n{code}" for file_name, code in submission_repository.items()
        )
        template_file_list = "\n------------\n".join(
            f"{file_name}:\n{code}" for file_name, code in template_repository.items()
        )

        history: List[PyrisMessage] = dto.chat_history or []
        conversation_history = _render_conversation_history(history[-4:])

        # Prompt injection: task_template/task_description/student_submission, and
        # the student's own answers, must never be interpolated into the system
        # message (the model's highest-authority channel) or replayed as native
        # "human"/"assistant" chat turns (many models give the live conversational
        # channel similar behavior-defining weight) — a student could plant fake
        # instructions in a file name, comment, or quiz answer to steer the verdict.
        # Both are instead rendered into separate, clearly delimited data messages
        # (see exercise_data_prompt and conversation_history_prompt) that the system
        # prompt above explicitly instructs the model to treat as inert data only.
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    assess_user_answer_prompt,
                ),
                (
                    "human",
                    exercise_data_prompt,
                ),
                (
                    "human",
                    conversation_history_prompt,
                ),
            ]
        )

        if dto.questions_asked < dto.min_questions:
            rules = under_min_questions_rules
        elif dto.questions_asked >= dto.max_questions:
            rules = over_equal_max_questions_rules
        else:
            rules = between_min_max_questions_rules

        problem_statement: str = (
            dto.programming_exercise.problem_statement
            if dto.programming_exercise
            else ""
        )

        prompt_val = self.prompt.format_messages(
            template=template_file_list,
            task=problem_statement,
            files=submission_file_list,
            decision_rules=rules,
            conversation=conversation_history,
        )
        self.prompt = ChatPromptTemplate.from_messages(prompt_val)

        response = (self.prompt | self.pipeline).invoke({})

        token_usage = self.llm.tokens
        token_usage.pipeline = PipelineEnum.IRIS_ASSESS_USER_ANSWER
        self.tokens = token_usage

        return response
