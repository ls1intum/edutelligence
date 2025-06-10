from typing import Literal, List

from langchain_core.output_parsers import PydanticOutputParser

from .faq_rewriting import system_prompt_faq


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
        #faqs: List[],
        to_be_rewritten: str,
        **kwargs,
    ):
        #if not dto.to_be_rewritten:
        #    raise ValueError("You need to provide a text to rewrite")

        variant_prompts = {
            "faq": system_prompt_faq,
        }


        final_result = "this is the result of the rewriting"
        return final_result


