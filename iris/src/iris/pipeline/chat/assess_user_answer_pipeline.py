import logging
from typing import Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from pydantic import BaseModel

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from ..prompts.assess_user_answer_prompt import assess_user_answer_prompt

from ...common.pyris_message import PyrisMessage
from ...llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
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
    default_prompt: PromptTemplate
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
            model = "gpt-4.1"
        else:
            model = "gpt-4.1-mini"

        request_handler = ModelVersionRequestHandler(version=model)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )

        # Load prompt from file
        prompt_str = assess_user_answer_prompt

        self.output_parser = StrOutputParser()
        # Create the prompt
        self.default_prompt = PromptTemplate(
            template=prompt_str,
            input_variables=["template", "task", "files", "chat_history", "min_questions", "max_questions"]
        )
        # Create the pipeline
        self.pipeline = self.llm | self.output_parser

    @traceable(name="Assess User Answer Pipeline")
    def __call__(
            self,
            template_repository: Dict[str, str],
            submission_repository: Dict[str, str],
            chat_history: List[PyrisMessage],
            problem_statement: str,
            min_questions: int,
            max_questions: int,
            questions_asked: int
    ) -> str:
        """
        Runs the pipeline
            :return: Selected file content
        """
        logger.info("Running assess user answer pipeline...")

        submission_file_list = "\n------------\n".join(
            [f"{file_name}:\n{code}" for file_name, code in submission_repository.items()]
        )
        template_file_list = "\n------------\n".join(
            [f"{file_name}:\n{code}" for file_name, code in template_repository.items()]
        )

        chat_history_list = "\n".join(
            f"{message.sender}: {message.contents[0].text_content}"
            for message in chat_history
            if message.contents
            and len(message.contents) > 0
            and message.contents[0].text_content
        )

        response = (
            (self.default_prompt | self.pipeline)
            .with_config({"run_name": "Assess User Answer Pipeline"})
            .invoke(
                {
                    "template": template_file_list,
                    "task": problem_statement,
                    "files": submission_file_list,
                    "chat_history": chat_history_list,
                    "min_questions": min_questions,
                    "max_questions": max_questions,
                    "questions_asked": questions_asked
                }
            )
        )
        token_usage = self.llm.tokens
        token_usage.pipeline = PipelineEnum.IRIS_ASSESS_USER_ANSWER
        self.tokens = token_usage
        return response.replace("{", "{{").replace("}", "}}")
