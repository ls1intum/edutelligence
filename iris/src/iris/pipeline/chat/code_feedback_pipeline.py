import os
from typing import Dict, List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.token_usage_dto import TokenUsageDTO
from iris.tracing import observe

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

logger = get_logger(__name__)


class FileSelectionDTO(BaseModel):
    question: str
    files: Dict[str, str]
    feedbacks: str

    def __str__(self):
        return (
            f'FileSelectionDTO(files="{self.files}", query="{self.query}", build_logs="{self.build_logs}", '
            f'exercise_title="{self.exercise_title}", problem_statement="{self.problem_statement}")'
        )


class CodeFeedbackPipeline(SubPipeline):
    """Code feedback pipeline that produces issues from student code."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: StatusCallback
    default_prompt: PromptTemplate
    output_parser: StrOutputParser
    tokens: TokenUsageDTO
    variant: str

    def __init__(
        self,
        callback: Optional[StatusCallback] = None,
        variant: str = "default",
        local: bool = False,
    ):
        super().__init__(implementation_id="code_feedback_pipeline_reference_impl")
        self.callback = callback
        self.variant = variant

        # Set up the language model
        completion_args = CompletionArguments(
            temperature=0, max_tokens=1024, response_format="text"
        )

        if local:
            if variant == "advanced":
                model = "gpt-oss:120b"
            else:
                model = "gpt-oss:120b"
        else:
            if variant == "advanced":
                model = "gpt-4.1"
            else:
                model = "gpt-4.1-mini"

        request_handler = ModelVersionRequestHandler(version=model)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )

        # Load prompt from file
        dirname = os.path.dirname(__file__)
        with open(
            os.path.join(dirname, "../prompts/code_feedback_prompt.txt"),
            "r",
            encoding="utf-8",
        ) as file:
            prompt_str = file.read()

        self.output_parser = StrOutputParser()
        # Create the prompt
        self.default_prompt = PromptTemplate(
            template=prompt_str,
            input_variables=["files", "feedbacks", "chat_history", "question"],
        )
        # Create the pipeline
        self.pipeline = self.llm | self.output_parser

    @observe(name="Code Feedback Pipeline")
    def __call__(
        self,
        repository: Dict[str, str],
        chat_history: List[PyrisMessage],
        question: PyrisMessage,
        feedbacks: List[FeedbackDTO],
        build_logs: List[BuildLogEntryDTO],
        build_failed: bool,
        problem_statement: str,
    ) -> str:
        """
        Runs the pipeline
            :param query: The query
            :return: Selected file content
        """
        logger.info("Running code feedback pipeline...")

        logs = (
            "The build was successful."
            if not build_failed
            else (
                "\n".join(
                    str(log) for log in build_logs if "~~~~~~~~~" not in log.message
                )
            )
        )

        file_list = "\n------------\n".join(
            [f"{file_name}:\n{code}" for file_name, code in repository.items()]
        )
        feedback_list = (
            "\n".join(
                [
                    f"Case: {feedback.test_case_name}. Credits: {feedback.credits}. Info: {feedback.text}"
                    for feedback in feedbacks
                ]
            )
            if feedbacks
            else "No feedbacks."
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
            .with_config({"run_name": "Code Feedback Pipeline"})
            .invoke(
                {
                    "files": file_list,
                    "feedbacks": feedback_list,
                    "chat_history": chat_history_list,
                    "question": str(question),
                    "build_log": logs,
                    "problem_statement": problem_statement,
                }
            )
        )
        token_usage = self.llm.tokens
        token_usage.pipeline = PipelineEnum.IRIS_CODE_FEEDBACK
        self.tokens = token_usage
        return response.replace("{", "{{").replace("}", "}}")
