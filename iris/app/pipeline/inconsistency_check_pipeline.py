import logging
from typing import Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable

from app.common.PipelineEnum import PipelineEnum
from app.domain import InconsistencyCheckPipelineExecutionDTO
from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.llm.langchain.iris_langchain_chat_model import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.web.status.status_update import InconsistencyCheckCallback
from app.pipeline.prompts.inconsistency_check_prompts import basic_prompt

logger = logging.getLogger(__name__)


class InconsistencyCheckPipeline(Pipeline):
    pipeline: Runnable
    llm: IrisLangchainChatModel
    callback: InconsistencyCheckCallback

    def __init__(self, callback: Optional[InconsistencyCheckCallback] = None):
        super().__init__(implementation_id="inconsistency_check_pipeline")
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(
                    gpt_version_equivalent=4.5,
                    context_length=16385,
                )
            ),
            completion_args=completion_args,
        )
        self.prompt = PromptTemplate.from_template(basic_prompt)
        self.pipeline = self.prompt | self.llm | StrOutputParser()
        self.callback = callback
        self.tokens = []

    @traceable(name="Inconsistency Check Pipeline")
    def __call__(self, dto: InconsistencyCheckPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline to check for inconsistencies in the exercise
        :param dto: execution data transfer object
        :param kwargs: The keyword arguments
        """

        if not dto.exercise:
            logger.error("Inconsistency check pipeline requires an exercise")
            raise ValueError("Exercise is required")

        logger.info("Running inconsistency check pipeline...")
        self.callback.in_progress()

        overall_response: str = ""

        for template_file_path, template_file_content in dto.exercise.template_repository.items():
            template_repository = "\n".join(
                f"<File path='{template_file_path}'>\n{template_file_content}</File>"
                
            )

            if template_file_path in dto.exercise.solution_repository.keys():
                solution_file_content = dto.exercise.solution_repository[template_file_path]
                solution_repository = f"<File path='{template_file_path}'>\n{solution_file_content}</File>"
            else:
                solution_repository = "\n".join(
                    f"<File path='{file_path}'>\n{file_content}</File>"
                    for file_path, file_content in dto.exercise.solution_repository.items()
                )
                logging.warning(f"Solution file for {template_file_path} not found, using all solution files: {dto.exercise.solution_repository.keys().join(', ')}")

            response: str = self.pipeline.invoke(
                {
                    "problem_statement": dto.exercise.problem_statement,
                    "solution_repository": solution_repository,
                    "template_repository": template_repository,
                }
            )

            overall_response += ('\n' if overall_response else '') + response
            self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_INCONSISTENCY_CHECK)

        self.callback.done(final_result=overall_response, tokens=self.tokens)
