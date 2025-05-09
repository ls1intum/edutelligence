import json
import logging
from typing import Literal, Optional, List, Dict

from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
)

from app.common.PipelineEnum import PipelineEnum
from app.common.pyris_message import PyrisMessage, IrisMessageRole
from app.domain.data.text_message_content_dto import TextMessageContentDTO
from app.domain.rewriting_pipeline_execution_dto import RewritingPipelineExecutionDTO
from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.pipeline import Pipeline
from app.pipeline.prompts.faq_consistency_prompt import faq_consistency_prompt
from app.pipeline.prompts.rewriting_prompts import (
    system_prompt_faq,
    system_prompt_problem_statement,
)
from app.retrieval.faq_retrieval import FaqRetrieval
from app.vector_database.database import VectorDatabase
from app.web.status.status_update import RewritingCallback

logger = logging.getLogger(__name__)


class RewritingPipeline(Pipeline):
    callback: RewritingCallback
    request_handler: CapabilityRequestHandler
    output_parser: PydanticOutputParser
    variant: Literal["faq", "problem_statement"]

    def __init__(
        self, callback: RewritingCallback, variant: Literal["faq", "problem_statement"]
    ):
        super().__init__(implementation_id="rewriting_pipeline_reference_impl")
        self.callback = callback
        self.request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=4.5,
                context_length=16385,
            )
        )

        self.db = VectorDatabase()
        self.tokens = []
        self.variant = variant
        self.faq_retriever = FaqRetrieval(self.db.client)

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

        format_args = {"rewritten_text": dto.to_be_rewritten}

        prompt = variant_prompts[self.variant].format(**format_args)
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
        inconsistencies = []
        improvement = ""
        suggestions = []

        if self.variant == "faq":
            faqs = self.faq_retriever.get_faqs_from_db(
                course_id=dto.course_id, search_text=response, result_limit=10
            )
            consistency_result = self.check_faq_consistency(faqs, final_result)

            if "inconsistent" in consistency_result["type"].lower():
                logging.warning("Detected inconsistencies in FAQ retrieval.")
                inconsistencies = parse_inconsistencies(consistency_result["faqs"])
                improvement = consistency_result["improved version"]
                suggestions = consistency_result["suggestion"]

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

        consistency_prompt = faq_consistency_prompt.format(
            faqs=properties_list, final_result=final_result
        )

        prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=consistency_prompt)],
        )

        response = self.request_handler.chat(
            [prompt], CompletionArguments(temperature=0.0), tools=None
        )

        self._append_tokens(response.token_usage, PipelineEnum.IRIS_REWRITING_PIPELINE)
        result = response.contents[0].text_content
        data = json.loads(result)

        result_dict = {}

        keys_to_check = ["type", "message", "faqs", "suggestion", "improved version"]

        for key in keys_to_check:
            if key in data:
                result_dict[key] = data[key]
        logging.info(faqs)
        logging.info(f"Consistency FAQ consistency check response: {result_dict}")

        return result_dict


def parse_inconsistencies(inconsistencies: List[Dict[str, str]]) -> List[str]:
    logging.info("parse consistency")
    parsed_inconsistencies = [
        f"FAQ ID: {entry['faq_id']}, Title: {entry['faq_question_title']}, Answer: {entry['faq_question_answer']}"
        for entry in inconsistencies
    ]
    return parsed_inconsistencies
