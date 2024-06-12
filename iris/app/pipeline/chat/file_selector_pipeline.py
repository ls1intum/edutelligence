import logging
import os
from typing import Dict, Optional, List

from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from pydantic import BaseModel

from ...domain import PyrisMessage
from ...domain.data.feedback_dto import FeedbackDTO
from ...llm import CapabilityRequestHandler, RequirementList
from ...llm import CompletionArguments
from ...llm.langchain import IrisLangchainChatModel
from ...pipeline import Pipeline
from ...pipeline.chat.output_models.output_models.selected_file_model import (
    SelectedFiles,
)
from ...web.status.status_update import StatusCallback

logger = logging.getLogger(__name__)


class FileSelectionDTO(BaseModel):
    question: str
    files: Dict[str, str]
    feedbacks: str

    def __str__(self):
        return (
            f'FileSelectionDTO(files="{self.files}", query="{self.query}", build_logs="{self.build_logs}", '
            f'exercise_title="{self.exercise_title}", problem_statement="{self.problem_statement}")'
        )


class FileSelectorPipeline(Pipeline):
    """File selector pipeline that selects the relevant file from a list of files."""

    llm: IrisLangchainChatModel
    pipeline: Runnable
    callback: StatusCallback
    default_prompt: PromptTemplate
    output_parser: PydanticOutputParser

    def __init__(self, callback: Optional[StatusCallback] = None):
        super().__init__(implementation_id="file_selector_pipeline_reference_impl")
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=3.5,
                context_length=4096,
                vendor="OpenAI",
                json_mode=True,
            )
        )
        completion_args = CompletionArguments(
            temperature=0, max_tokens=500, response_format="JSON"
        )
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.callback = callback
        # Load prompt from file
        dirname = os.path.dirname(__file__)
        with open(
            os.path.join(dirname, "../prompts/file_selector_prompt.txt"), "r"
        ) as file:
            prompt_str = file.read()

        self.output_parser = PydanticOutputParser(pydantic_object=SelectedFiles)
        # Create the prompt
        self.default_prompt = PromptTemplate(
            template=prompt_str,
            input_variables=["file_names", "feedbacks", "chat_history", "question"],
            partial_variables={
                "format_instructions": self.output_parser.get_format_instructions()
            },
        )
        logger.debug(self.output_parser.get_format_instructions())
        # Create the pipeline
        self.pipeline = self.llm | self.output_parser

    @traceable(name="File Selector Pipeline")
    def __call__(
        self,
        repository: Dict[str, str],
        chat_history: List[PyrisMessage],
        question: PyrisMessage,
        feedbacks: List[FeedbackDTO],
    ) -> List[str]:
        """
        Runs the pipeline
            :param query: The query
            :return: Selected file content
        """
        logger.info("Running file selector pipeline...")

        file_list = "\n".join(repository.keys())
        feedback_list = "\n".join(["Case: {}. Credits: {}. Info: {}".format(
            feedback.test_case_name,
            feedback.credits, feedback.text)
            for feedback in feedbacks]) if feedbacks else "No feedbacks."
        chat_history_list = "\n".join([str(message) for message in chat_history])
        response = (self.default_prompt | self.pipeline).with_config({"run_name": "File Selector Prompt"}).invoke(
            {
                "file_names": file_list,
                "feedbacks": feedback_list,
                "chat_history": chat_history_list,
                "question": str(question),
            }
        )
        return response.selected_files
