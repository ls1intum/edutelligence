import logging
from typing import Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from pydantic import BaseModel

from iris.common.message_converters import (
    convert_iris_message_to_langchain_message,
)
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from ..prompts.assess_user_answer_prompt import (
    assess_user_answer_prompt,
    under_min_questions_rules,
    over_equal_max_questions_rules,
    between_min_max_questions_rules,
)

from ...common.pyris_message import PyrisMessage
from ...domain.chat.ask_user_chat.ask_user_chat_pipeline_execution_dto import (
    AskUserPipelineExecutionDTO,
)
from ...llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from ...llm.langchain import IrisLangchainChatModel
from ...web.status.status_update import StatusCallback
from ..sub_pipeline import SubPipeline

logger = logging.getLogger(__name__)


class FileSelectionDTO(BaseModel):
    question: str
    files: Dict[str, str]

    def __str__(self):
        return (
            f'FileSelectionDTO(files="{self.files}", '
            f'exercise_title="{self.exercise_title}", problem_statement="{self.problem_statement}")'
        )


class AssessUserAnswerPipeline(SubPipeline):
    """Pipeline that assesses a given answer by the student to decide whether it is convincing or not"""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: StatusCallback
    prompt: ChatPromptTemplate
    output_parser: StrOutputParser
    tokens: TokenUsageDTO
    variant: str

    def __init__(
        self, callback: Optional[StatusCallback] = None, variant: str = "default"
    ):
        super().__init__(implementation_id="assess_user_answer_pipeline_reference_impl")
        self.callback = callback
        self.variant = variant

        # Set up the language model
        completion_args = CompletionArguments(
            temperature=0, max_tokens=1024, response_format="text"
        )

        if variant == "advanced":
            model = "oai-gpt-52"
        else:
            model = "oai-gpt-5-mini"

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

        submission_file_list = "\n------------\n".join(
            [
                f"{file_name}:\n{code}"
                for file_name, code in dto.submission.repository.items()
            ]
        )
        template_file_list = "\n------------\n".join(
            [
                f"{file_name}:\n{code}"
                for file_name, code in dto.exercise.template_repository.items()
            ]
        )

        history: List[PyrisMessage] = dto.chat_history or []

        # Add the conversation to the prompt
        chat_history_messages = [
            convert_iris_message_to_langchain_message(message)
            for message in history[-4:]
        ]

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    assess_user_answer_prompt,
                ),
                *chat_history_messages,
            ]
        )



        if dto.questions_asked < dto.min_questions:
            rules = under_min_questions_rules
        elif dto.questions_asked >= dto.max_questions:
            rules = over_equal_max_questions_rules
        else:
            rules = between_min_max_questions_rules

        prompt_val = self.prompt.format_messages(template=template_file_list, task=dto.exercise.problem_statement,
                                                     files=submission_file_list, decision_rules=rules)
        self.prompt = ChatPromptTemplate.from_messages(prompt_val)


        response = (self.prompt | self.pipeline).invoke({})

        token_usage = self.llm.tokens
        token_usage.pipeline = PipelineEnum.IRIS_ASSESS_USER_ANSWER
        self.tokens = token_usage

        return response
