import logging

from nebula.transcript.config import Config
from nebula.transcript.llm_utils import get_openai_client


def ask_gpt_for_slide_number(image_b64: str, llm_id: str | None = None) -> int | None:
    """
    Use GPT Vision to detect the slide number from a base64 image.
    Supports both Azure OpenAI and OpenAI.com based on `llm_id`.

    Args:
        image_b64 (str): base64-encoded image string.
        llm_id (str | None): Optional override for GPT Vision model ID.

    Returns:
        int | None: Detected slide number, or None if unknown.
    """
    try:
        # Use configured LLM if not explicitly given
        llm_id = llm_id or Config.get_gpt_vision_llm_id()
        client, model_or_deployment = get_openai_client(llm_id)

        response = client.chat.completions.create(
            model=model_or_deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What slide number is visible? Only number, or 'Null'.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        )

        content = response.choices[0].message.content.strip().lower()
        if "null" in content or "unknown" in content:
            return None

        digits = "".join(filter(str.isdigit, content))
        return int(digits) if digits else None

    except Exception as e:
        logging.warning("GPT Vision failed: %s", e)
        return None
