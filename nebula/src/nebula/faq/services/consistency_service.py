import json
import logging
from typing import re, Any
from nebula.faq.prompts.faq_consistency_prompt import faq_consistency_prompt
from nebula.llm.openai_client import get_openai_client
from nebula.faq.domains.data.faq_dto import FaqConsistencyResponse


logger = logging.getLogger("nebula.faq.consistency_service")


def check_faq_consistency(faqs: list, to_be_checked) -> dict:
    """
    Check the consistency of FAQs and return a dictionary with consistency status and suggestions.
    """
    # Placeholder for actual consistency check logic
    consistent = False  # Assume consistent for now
    inconsistencies = ["inconsistency1", "inconsistency2"]  # Example inconsistencies
    suggestions = ["suggestion1", "suggestion2"]  # Example suggestions
    improvement = "No improvements needed."

    try:
        client, deployment = get_openai_client("azure-gpt-4-omni")

        consistency_prompt = faq_consistency_prompt.format(
            faqs=faqs, final_result=to_be_checked
        )

        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": consistency_prompt,
                },
            ],
        )

        consistency_result = response.choices[0].message.content.strip()

        parsed_result = parse_consistency_response(consistency_result)
        logging.info("Parsed consistency result: %s", parsed_result)
        logging.info("Parsed consistency result type: %s", type(parsed_result))
        logging.info ("Parsed faqs content: %s", parsed_result.get("faqs", []))
        logging.info("Parsed faqs type: %s", type(parsed_result.get("faqs", [])))
        logging.info("Parsed improved version content: %s", parsed_result.get("improved_version", ""))

        response_model = FaqConsistencyResponse(
            consistent=parsed_result.get("type") == "consistent",
            inconsistencies=parsed_result.get("inconsistencies", []),
            improvement=parsed_result.get("improvement", ""),
            faqIds=parsed_result.get("faqIds", [])
        )

        return response_model


    except Exception as e:
        logger.error("Error rewriting FAQ text: %s", e)
        raise EnvironmentError("Rewriting failed")


def parse_consistency_response(response_str: str) -> dict[str, Any]:
    """
    Parse the string response from the LLM and return the structured consistency check result.
    Expected keys: type, faqs, message, suggestion, improved version
    """
    try:
        if response_str.startswith("```json"):
            response_str = response_str.removeprefix("```json").removesuffix("```").strip()
        elif response_str.startswith("```"):
            response_str = response_str.removeprefix("```").removesuffix("```").strip()
        data = json.loads(response_str)
        logging.info("Parsed response as JSON successfully.")
        logging.info("Response type: %s", type(data))
        logging.info("Response content: %s", data)
        logging.info(type(response_str))
        return data
    except json.JSONDecodeError:
        raise TypeError("Response is not a valid JSON string: %s" % response_str)

