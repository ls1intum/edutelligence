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
from iris.domain.variant.variant import Variant
from iris.llm import (
    CompletionArguments,
    LlmRequestHandler,
)
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


class RewritingPipeline(Pipeline):
    """RewritingPipeline processes text rewriting requests by interfacing with a language model via a capability
     request handler.

    It formats the prompt according to the selected variant, processes the rewriting, and then notifies the callback
     when complete.
    """

    PIPELINE_ID = "rewriting_pipeline"
    ROLES = {"rewriting", "consistency"}
    VARIANT_DEFS = [
        ("faq", "Default FAQ Variant", "Default FAQ rewriting variant."),
        (
            "problem_statement",
            "Default Variant",
            "Default Problem statement rewriting variant.",
        ),
    ]

    callback: RewritingCallback
    rewriting_handler: LlmRequestHandler
    consistency_handler: LlmRequestHandler
    output_parser: PydanticOutputParser
    variant_id: Literal["faq", "problem_statement"]

    def __init__(
        self,
        callback: RewritingCallback,
        variant: Variant,
        local: bool = False,
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.callback = callback
        self.db = VectorDatabase()
        self.variant_id = cast(Literal["faq", "problem_statement"], variant.variant_id)
        rewriting_model = variant.model("rewriting", local)
        consistency_model = variant.model("consistency", local)
        self.rewriting_handler = LlmRequestHandler(model_id=rewriting_model)
        self.consistency_handler = LlmRequestHandler(model_id=consistency_model)
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


def parse_faq_inconsistencies(inconsistencies: List[Dict[str, str]]) -> List[str]:
    parsed_inconsistencies = [
        f"FAQ ID: {entry["faq_id"]}, Title: {entry["faq_question_title"]}, Answer: {entry["faq_question_answer"]}"
        for entry in inconsistencies
    ]
    return parsed_inconsistencies
