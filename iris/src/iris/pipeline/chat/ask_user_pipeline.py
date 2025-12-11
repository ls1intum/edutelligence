import logging
import os
from typing import Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from pydantic import BaseModel

from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from ..prompts.ask_user_prompt import generate_user_question_prompt

from ...common.pyris_message import PyrisMessage
from ...domain.data.build_log_entry import BuildLogEntryDTO
from ...domain.data.feedback_dto import FeedbackDTO
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


class AskUserPipeline(SubPipeline):
    """Pipeline that produces assessment question from submitted code and task"""

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
        super().__init__(implementation_id="ask_user_pipeline_reference_impl")
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
        prompt_str = generate_user_question_prompt

        self.output_parser = StrOutputParser()
        # Create the prompt
        self.default_prompt = PromptTemplate(
            template=prompt_str,
            input_variables=["template", "files", "chat_history"],
        )
        # Create the pipeline
        self.pipeline = self.llm | self.output_parser

    @traceable(name="Ask User Pipeline")
    def __call__(
            self,
            repository: Dict[str, str],
            chat_history: List[PyrisMessage],
            problem_statement: str,
    ) -> str:
        """
        Runs the pipeline
            :return: Selected file content
        """
        logger.info("Running ask user pipeline...")

        file_list = "\n------------\n".join(
            [f"{file_name}:\n{code}" for file_name, code in repository.items()]
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
            .with_config({"run_name": "Ask User Pipeline"})
            .invoke(
                {
                    "files": file_list,
                    "chat_history": chat_history_list,
                    "problem_statement": problem_statement,
                }
            )
        )
        token_usage = self.llm.tokens
        token_usage.pipeline = PipelineEnum.IRIS_ASK_USER
        self.tokens = token_usage
        return response.replace("{", "{{").replace("}", "}}")
