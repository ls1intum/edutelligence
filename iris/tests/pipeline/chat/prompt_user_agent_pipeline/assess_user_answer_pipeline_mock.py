from typing import Optional
from langsmith import traceable

from iris.common.token_usage_dto import TokenUsageDTO
from iris.domain.chat.prompt_user_chat.prompt_user_chat_pipeline_execution_dto import PromptUserPipelineExecutionDTO
from iris.web.status.status_update import StatusCallback
from iris.pipeline.sub_pipeline import SubPipeline

class AssessUserAnswerPipelineMock(SubPipeline):
    """Pipeline mock that assesses a given answer always as too vague, so another question must be generated (next_question is returned)"""

    callback: StatusCallback
    variant: str
    tokens: TokenUsageDTO = None

    def __init__(
            self, callback: Optional[StatusCallback] = None, variant: str = "default"
    ):
        super().__init__(implementation_id="assess_user_answer_pipeline_reference_impl")
        self.callback = callback
        self.variant = variant

    @traceable(name="Assess User Answer Pipeline Mock")
    def __call__(
            self,
            dto: PromptUserPipelineExecutionDTO
    ) -> str:
        """
        Runs the pipeline
            :return: Assessment result
        """

        return """{
            "verdict": "next_question",
            "reasoning": "This answer was too vague. Another question is needed to assess the student's understanding."
        }"""
