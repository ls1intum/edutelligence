import json
import logging
from typing import Any, Dict, List, Literal, Optional, cast

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)

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
from iris.llm.llm_manager import LlmManager
from iris.pipeline import Pipeline
from iris.pipeline.prompts.rewriting_prompts import (
    system_prompt_faq,
    system_prompt_problem_statement,
)
from iris.web.status.status_update import RewritingCallback

from ..retrieval.faq_retrieval import FaqRetrieval
from ..vector_database.database import VectorDatabase
from .prompts.faq_consistency_prompt import faq_consistency_prompt

logger = logging.getLogger(__name__)


class RewritingPipeline(Pipeline[RewritingVariant]):
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
        self.db = VectorDatabase()
        self.request_handler = ModelVersionRequestHandler(
            llm_manager=LlmManager(), version="gpt-4.1"
        )
        self.tokens = []
        self.variant = variant
        self.faq_retriever = FaqRetrieval(self.db.client)

    def __call__(
        self,
        dto: RewritingPipelineExecutionDTO,
        prompt: Optional[ChatPromptTemplate] = None,
        **kwargs: Any,
    ) -> None:
        if not dto.to_be_rewritten:
            raise ValueError("You need to provide a text to rewrite")

        variant_prompts = {
            "faq": system_prompt_faq,
            "problem_statement": system_prompt_problem_statement,
        }
        formatted_prompt = variant_prompts[self.variant].format(
            rewritten_text=dto.to_be_rewritten,
        )
        system_message = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(textContent=formatted_prompt)],
        )

        response = self.request_handler.chat(
            [system_message], CompletionArguments(temperature=0.4), tools=None
        )
        self._append_tokens(response.token_usage, PipelineEnum.IRIS_REWRITING_PIPELINE)
        response_text = cast(TextMessageContentDTO, response.contents[0]).text_content

        # remove ``` from start and end if exists
        if response_text.startswith("```") and response_text.endswith("```"):
            response_text = response_text[3:-3]
            if response_text.startswith("markdown"):
                response_text = response_text[8:]
            response_text = response_text.strip()

        final_result = response_text
        inconsistencies: List[str] = []
        improvement = ""
        suggestions: List[Any] = []

        if self.variant == "faq":
            faqs = self.faq_retriever.get_faqs_from_db(
                course_id=dto.course_id, search_text=response_text, result_limit=10
            )
            consistency_result = self.check_faq_consistency(faqs, final_result)
            faq_type = consistency_result.get("type", "").lower()
            if "inconsistent" in faq_type:
                logging.warning("Detected inconsistencies in FAQ retrieval.")
                faq_list: Any = consistency_result.get("faqs", [])
                if isinstance(faq_list, list):
                    inconsistencies = parse_faq_inconsistencies(faq_list)
                improvement = consistency_result.get("improved version", "")
                suggestion_result: Any = consistency_result.get("suggestion", [])
                if isinstance(suggestion_result, list):
                    suggestions = suggestion_result

        self.callback.done(
            final_result=final_result,
            tokens=self.tokens,
            inconsistencies=inconsistencies,
            improvement=improvement,
            suggestions=suggestions,
        )

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

        consistency_message = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(textContent=consistency_prompt)],
        )

        response = self.request_handler.chat(
            [consistency_message], CompletionArguments(temperature=0.0), tools=None
        )

        self._append_tokens(response.token_usage, PipelineEnum.IRIS_REWRITING_PIPELINE)
        result = cast(TextMessageContentDTO, response.contents[0]).text_content

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
        return [
            RewritingVariant(
                variant_id="faq",
                name="Default FAQ Variant",
                description="Default FAQ rewriting variant.",
                rewriting_model="gpt-4.1",
                consistency_model="gpt-4.1",
            ),
            RewritingVariant(
                variant_id="problem_statement",
                name="Default Variant",
                description="Default Problem statement rewriting variant.",
                rewriting_model="gpt-4.1",
            ),
        ]


def parse_faq_inconsistencies(inconsistencies: List[Dict[str, str]]) -> List[str]:
    parsed_inconsistencies = [
        f"FAQ ID: {entry["faq_id"]}, Title: {entry["faq_question_title"]}, Answer: {entry["faq_question_answer"]}"
        for entry in inconsistencies
    ]
    return parsed_inconsistencies
