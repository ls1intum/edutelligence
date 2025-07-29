import logging

from nebula.faq.prompts.faq_consistency_prompt import faq_consistency_prompt
from nebula.llm.openai_client import get_openai_client
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
        logging.info("Consistency check response: %s", consistency_result)

        return {
            "consistent": consistent,
            "inconsistencies": inconsistencies,
            "suggestions": suggestions,
            "improvement": improvement
        }

    except Exception as e:
        logger.error("Error rewriting FAQ text: %s", e)
        raise EnvironmentError("Rewriting failed")


