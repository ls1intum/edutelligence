import logging

from nebula.faq.prompts.rewrite_faq_prompt import system_prompt_faq_rewriting
from nebula.llm.openai_client import get_openai_client

logger = logging.getLogger("nebula.faq.rewrite_service")


def rewrite_faq_text(to_be_rewritten: str) -> str:

    try:
        client, deployment = get_openai_client("azure-gpt-4-omni")

        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt_faq_rewriting.format(
                        rewritten_text=to_be_rewritten
                    ),
                },
            ],
        )

        to_be_rewritten = response.choices[0].message.content.strip()
        return to_be_rewritten

    except Exception as e:
        logger.error("Error rewriting FAQ text: %s", e)
        raise EnvironmentError("Rewriting failed") from e
