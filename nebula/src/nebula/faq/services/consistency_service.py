import json
import logging
from typing import Any

from nebula.faq.domains.data.faq_dto import FaqConsistencyResponse, FaqDTO
from nebula.faq.prompts.faq_consistency_prompt import faq_consistency_prompt
from nebula.llm.openai_client import get_openai_client

logger = logging.getLogger("nebula.faq.consistency_service")


def check_faq_consistency(
    faqs: list[FaqDTO] | None, to_be_checked
) -> FaqConsistencyResponse:
    """
    Check the consistency of FAQs and return a dictionary with consistency status and suggestions.
    """

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
        logging.info("Parsed faqs content: %s", parsed_result.get("faqs", []))
        logging.info("Parsed faqs type: %s", type(parsed_result.get("faqs", [])))
        logging.info(
            "Parsed improved version content: %s",
            parsed_result.get("improved_version", ""),
        )

        response_model = FaqConsistencyResponse(
            consistent=parsed_result.get("type") == "consistent",
            inconsistencies=parsed_result.get("inconsistencies", []),
            improvement=parsed_result.get("improvement", ""),
            faq_ids=parsed_result.get("faqIds", []),
        )

        return response_model

    except Exception as e:
        logger.error("Error rewriting FAQ text: %s", e)
        raise EnvironmentError("Rewriting failed") from e


def parse_consistency_response(response_str: str) -> dict[str, Any]:
    """
    Parse the string response from the LLM and return the structured consistency check result.
    Expected keys: type, faqs, message, suggestion, improved version
    """
    try:
        if response_str.startswith("```json"):
            response_str = (
                response_str.removeprefix("```json").removesuffix("```").strip()
            )
        elif response_str.startswith("```"):
            response_str = response_str.removeprefix("```").removesuffix("```").strip()
        data = json.loads(response_str)
        logging.info("Parsed response as JSON successfully.")
        logging.info("Response type: %s", type(data))
        logging.info("Response content: %s", data)
        logging.info(type(response_str))
        return data
    except json.JSONDecodeError as exc:
        raise TypeError(f"Response is not a valid JSON string: {response_str}") from exc
