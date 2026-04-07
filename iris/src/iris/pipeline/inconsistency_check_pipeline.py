import re
from typing import Dict, List, Optional

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain import InconsistencyCheckPipelineExecutionDTO
from iris.domain.variant.inconsistency_check_variant import InconsistencyCheckVariant
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.langchain.iris_langchain_chat_model import IrisLangchainChatModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.inconsistency_check_prompts import (
    prettify_prompt,
    solver_prompt,
)
from iris.tracing import observe
from iris.web.status.status_update import InconsistencyCheckCallback

logger = get_logger(__name__)


class InconsistencyCheckPipeline(Pipeline[InconsistencyCheckVariant]):
    """InconsistencyCheckPipeline checks for consistency issues within an exercise by evaluating files from template
     and solution repositories.

    It invokes a solver pipeline to identify potential inconsistencies, then uses a prettify pipeline to generate a
     summary report.
    """

    llm: IrisLangchainChatModel
    callback: InconsistencyCheckCallback

    solver: Runnable
    prettify: Runnable

    def __init__(
        self, callback: Optional[InconsistencyCheckCallback] = None, local: bool = False
    ):
        super().__init__(implementation_id="inconsistency_check_pipeline")
        completion_args = CompletionArguments()

        self.llm = IrisLangchainChatModel(
            request_handler=ModelVersionRequestHandler(
                version="gpt-oss:120b" if local else "gpt-5-mini"
            ),
            completion_args=completion_args,
        )
        self.solver_prompt = PromptTemplate.from_template(solver_prompt)
        self.solver = self.solver_prompt | self.llm

        self.prettify_prompt = PromptTemplate.from_template(prettify_prompt)
        self.prettify = self.prettify_prompt | self.llm

        self.callback = callback
        self.tokens = []

    @observe(name="Inconsistency Check Pipeline")
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

        # First, for each file in the exercise, we will check for consistency issues via the solver pipeline
        consistency_issues: Dict[str, str] = {}
        file_paths = set(dto.exercise.template_repository.keys()) | set(
            dto.exercise.solution_repository.keys()
        )
        solver_inputs = [
            {
                "file_path": file_path,
                "problem_statement": dto.exercise.problem_statement,
                "template_file": dto.exercise.template_repository.get(
                    file_path, "no file found"
                ),
                "solution_file": dto.exercise.solution_repository.get(
                    file_path, "no file found"
                ),
            }
            for file_path in file_paths
        ]
        file_responses = self.solver.map().invoke(solver_inputs)
        consistency_issues = {
            file_path: response.content
            for file_path, response in zip(file_paths, file_responses)
        }

        # Second, we will prettify the consistency issues and provide a summary using the prettify pipeline
        formatted_consistency_issues = "\n".join(
            [
                f"<PotentialFileIssues filePath=`{file_path}`>\n{issues}\n</PotentialFileIssues>"
                for file_path, issues in consistency_issues.items()
            ]
        )
        summary_response = self.prettify.invoke(
            {
                "problem_statement": dto.exercise.problem_statement,
                "consistency_issues": formatted_consistency_issues,
            }
        )

        result = summary_response.content.strip()

        # Remove ``` from start and end if exists
        if result.startswith("```") and result.endswith("```"):
            result = result[3:-3]
            if result.startswith("markdown"):
                result = result[8:]
            result = result.strip()

        # Remove first heading or heading containing 'Summary of Consistency Issues'
        result = re.sub(r"^#\s.*?\n", "", result)
        result = re.sub(r"^#+.*?Summary of Consistency Issues\s*\n", "", result)

        self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_INCONSISTENCY_CHECK)
        self.callback.done(final_result=result, tokens=self.tokens)

    @classmethod
    def get_variants(cls) -> List[InconsistencyCheckVariant]:
        """
        Returns available variants for the InconsistencyCheckPipeline.

        Returns:
            List of InconsistencyCheckVariant objects representing available variants
        """
        return [
            InconsistencyCheckVariant(
                variant_id="default",
                name="Default",
                description="Standard inconsistency check implementation with efficient model usage",
                cloud_solver_model="gpt-5-mini",
                local_solver_model="gpt-oss:120b",
            ),
        ]
