import json
from typing import Dict, List, Literal, Optional, cast

from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.domain.rewriting_pipeline_execution_dto import (
    RewritingPipelineExecutionDTO,
)
from iris.domain.variant.rewriting_variant import RewritingVariant
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.llm_configuration import resolve_role_models
from iris.pipeline import Pipeline
from iris.pipeline.prompts.rewriting_prompts import (
    system_prompt_faq,
    system_prompt_problem_statement,
)
from iris.tracing import observe
from iris.web.status.status_update import RewritingCallback

from ..retrieval.faq_retrieval import FaqRetrieval
from ..vector_database.database import VectorDatabase
from .prompts.faq_consistency_prompt import faq_consistency_prompt

logger = get_logger(__name__)


class RewritingPipeline(Pipeline[RewritingVariant]):
    """RewritingPipeline processes text rewriting requests by interfacing with a language model via a capability
     request handler.

    It formats the prompt according to the selected variant, processes the rewriting, and then notifies the callback
     when complete.
    """

    callback: RewritingCallback
    rewriting_handler: ModelVersionRequestHandler
    consistency_handler: ModelVersionRequestHandler
    output_parser: PydanticOutputParser
    variant_id: Literal["faq", "problem_statement"]

    def __init__(
        self,
        callback: RewritingCallback,
        variant: RewritingVariant,
        local: bool = False,
    ):
        super().__init__(implementation_id="rewriting_pipeline")
        self.callback = callback
        self.db = VectorDatabase()
        self.variant_id = cast(Literal["faq", "problem_statement"], variant.variant_id)
        rewriting_model = (
            variant.local_rewriting_model if local else variant.cloud_rewriting_model
        )
        consistency_model = (
            variant.local_consistency_model
            if local
            else variant.cloud_consistency_model
        )
        self.rewriting_handler = ModelVersionRequestHandler(version=rewriting_model)
        self.consistency_handler = ModelVersionRequestHandler(version=consistency_model)
        self.tokens = []
        self.faq_retriever = FaqRetrieval(self.db.client, local=local)

    @observe(name="Rewriting Pipeline")
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
        prompt = variant_prompts[self.variant_id].format(
            rewritten_text=dto.to_be_rewritten,
        )
        prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=prompt)],
        )

        response = self.rewriting_handler.chat(
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
        inconsistencies = []
        improvement = ""
        suggestions = []

        if self.variant_id == "faq":
            faqs = self.faq_retriever.get_faqs_from_db(
                course_id=dto.course_id, search_text=response, result_limit=10
            )
            consistency_result = self.check_faq_consistency(faqs, final_result)
            faq_type = consistency_result.get("type", "").lower()
            if "inconsistent" in faq_type:
                logger.warning("Detected inconsistencies in FAQ retrieval.")
                inconsistencies = parse_faq_inconsistencies(
                    consistency_result.get("faqs", [])
                )
                improvement = consistency_result.get("improved version", "")
                suggestions = consistency_result.get("suggestion", [])

        final_result = response
        self.callback.done(
            final_result=final_result,
            tokens=self.tokens,
            inconsistencies=inconsistencies,
            improvement=improvement,
            suggestions=suggestions,
        )

    @observe(name="FAQ Consistency Check")
    def check_faq_consistency(
        self, faqs: List[dict], final_result: str
    ) -> Dict[str, str]:
        """
        Checks the consistency of the given FAQs with the provided final_result.
        Returns "consistent" if there are no inconsistencies, otherwise returns "inconsistent".

        :param faqs: List of retrieved FAQs.
        :param final_result: The result to compare the FAQs against.

        """
        properties_list = [entry["properties"] for entry in faqs]

        if not faqs:
            return {"type": "consistent", "message": "No FAQs to check"}

        consistency_prompt = faq_consistency_prompt.format(
            faqs=properties_list, final_result=final_result
        )

        prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=consistency_prompt)],
        )

        response = self.consistency_handler.chat(
            [prompt], CompletionArguments(temperature=0.0), tools=None
        )

        self._append_tokens(response.token_usage, PipelineEnum.IRIS_REWRITING_PIPELINE)
        result = response.contents[0].text_content

        if result.startswith("```json"):
            result = result.removeprefix("```json").removesuffix("```").strip()
        elif result.startswith("```"):
            result = result.removeprefix("```").removesuffix("```").strip()

        data = json.loads(result)

        result_dict = {}
        keys_to_check = ["type", "message", "faqs", "suggestion", "improved version"]
        for key in keys_to_check:
            if key in data:
                result_dict[key] = data[key]
        return result_dict

    @classmethod
    def get_variants(cls) -> List[RewritingVariant]:
        """
        Returns available variants for the RewritingPipeline.

        Returns:
            List of RewritingVariant objects representing available variants
        """
        pipeline_id = "rewriting_pipeline"

        variants: list[RewritingVariant] = []
        for variant_id, name, description in [
            ("faq", "Default FAQ Variant", "Default FAQ rewriting variant."),
            (
                "problem_statement",
                "Default Variant",
                "Default Problem statement rewriting variant.",
            ),
        ]:
            rewriting_models = resolve_role_models(pipeline_id, variant_id, "rewriting")
            consistency_models = resolve_role_models(
                pipeline_id, variant_id, "consistency"
            )
            variants.append(
                RewritingVariant(
                    variant_id=variant_id,
                    name=name,
                    description=description,
                    cloud_rewriting_model=rewriting_models["cloud"],
                    local_rewriting_model=rewriting_models["local"],
                    cloud_consistency_model=consistency_models["cloud"],
                    local_consistency_model=consistency_models["local"],
                )
            )

        return variants


def parse_faq_inconsistencies(inconsistencies: List[Dict[str, str]]) -> List[str]:
    parsed_inconsistencies = [
        f"FAQ ID: {entry["faq_id"]}, Title: {entry["faq_question_title"]}, Answer: {entry["faq_question_answer"]}"
        for entry in inconsistencies
    ]
    return parsed_inconsistencies
