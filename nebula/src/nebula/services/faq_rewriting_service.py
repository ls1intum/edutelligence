import json
from typing import Literal, List, Optional

from langchain_core.output_parsers import PydanticOutputParser

from nebula.src.nebula.prompts.faq_rewriting import system_prompt_faq
from nebula.src.nebula.services.faq_service import faq_pb2


def format_faqs_for_openai(faqs: Optional[List[faq_pb2.FAQ]]) -> str:
    faqs = faqs or []
    print(f"Formatting {len(faqs)} FAQs for OpenAI")
    print (f"FAQs: {faqs}")
    return json.dumps([
        {
            "question_title": faq.question_title,
            "question_answer": faq.question_answer
        } for faq in faqs
    ], indent=2)


class FaqRewritingService:
    """FaqRewriter processes text rewriting requests by interfacing with a language model via a capability
     request handler.

    It formats the prompt according to the selected variant, processes the rewriting, and then notifies the callback
     when complete.
    """

    #request_handler: ModelVersionRequestHandler
    output_parser: PydanticOutputParser
    variant: Literal["faq", "problem_statement"]

    def __init__(
        self,
        variant: Literal["faq", "problem_statement"],
    ):
        #self.request_handler = ModelVersionRequestHandler(version="gpt-4.1")
        self.tokens = []
        self.variant = variant


    def rewrite_faq(
        self,
        to_be_rewritten: str,
        faqs: List[faq_pb2.FAQ] = None,
        **kwargs,
    ):

        # Select the appropriate system prompt based on the variant
        variant_prompts = {
            "faq": system_prompt_faq,
        }
        system_prompt = variant_prompts.get(self.variant, system_prompt_faq)
        faqs_text = format_faqs_for_openai(faqs)

        # Here, we would typically call the language model to process the rewriting.


        ##LLM Magic Placeholder


        #For demonstration purposes, we will simulate the rewriting process.
        final_result = "this is the result of the rewriting"
        return final_result


