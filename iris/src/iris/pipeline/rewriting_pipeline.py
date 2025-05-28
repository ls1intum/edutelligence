import logging
from typing import Literal, Optional, List

from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)

from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.rewriting_pipeline_execution_dto import (
    RewritingPipelineExecutionDTO,
)
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.pipeline import Pipeline
from iris.pipeline.prompts.rewriting_prompts import (
    system_prompt_faq,
    system_prompt_problem_statement,
)
from iris.web.status.status_update import RewritingCallback

from ..llm.external.model import LanguageModel
from ..domain import FeatureDTO

logger = logging.getLogger(__name__)


class RewritingPipeline(Pipeline):
    """RewritingPipeline processes text rewriting requests by interfacing with a language model via a capability
     request handler.

    It formats the prompt according to the selected variant, processes the rewriting, and then notifies the callback
     when complete.
    """

    callback: RewritingCallback
    request_handler: ModelVersionRequestHandler
    output_parser: PydanticOutputParser
    variant: Literal["faq", "problem_statement"]

    def __init__(
        self,
        callback: RewritingCallback,
        variant: Literal["faq", "problem_statement"],
    ):
        super().__init__(implementation_id="rewriting_pipeline_reference_impl")
        self.callback = callback
        self.request_handler = ModelVersionRequestHandler(version="gpt-4.1")
        self.tokens = []
        self.variant = variant

    def __call__(
        self,
        dto: RewritingPipelineExecutionDTO,
        prompt: Optional[ChatPromptTemplate] = None,
        **kwargs,
    ):
        if not dto.to_be_rewritten:
            raise ValueError("You need to provide a text to rewrite")

        variant_prompts = {
            "faq": system_prompt_faq,
            "problem_statement": system_prompt_problem_statement,
        }
        print(variant_prompts[self.variant])
        prompt = variant_prompts[self.variant].format(
            rewritten_text=dto.to_be_rewritten,
        )
        prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=prompt)],
        )

        response = self.request_handler.chat(
            [prompt], CompletionArguments(temperature=0.4), tools=None
        )
        self._append_tokens(response.token_usage, PipelineEnum.IRIS_REWRITING_PIPELINE)
        response = response.contents[0].text_content

        # remove ``` from start and end if exists
        if response.startswith("```") and response.endswith("```"):
            response = response[3:-3]
            if response.startswith("markdown"):
                response = response[8:]
            response = response.strip()

        final_result = response
        self.callback.done(final_result=final_result, tokens=self.tokens)

    @classmethod
    def get_variants(cls, available_llms: List[LanguageModel]) -> List[FeatureDTO]:
        """
        Returns available variants for the FaqIngestionPipeline based on available LLMs.

        Args:
            available_llms: List of available language models

        Returns:
            List of FeatureDTO objects representing available variants
        """
        return [
            FeatureDTO(
                id="faq",
                name="Default FAQ Variant",
                description="Default FAQ rewriting variant.",
            ),
            FeatureDTO(
                id="problem_statement",
                name="Default Variant",
                description="Default Problem statement rewriting variant.",
            )
        ]
