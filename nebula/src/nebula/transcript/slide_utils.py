import logging
from nebula.transcript.llm_utils import get_openai_client


def ask_gpt_for_slide_number(image_b64: str) -> int | None:
    """
    Use GPT-4o Vision to detect a visible slide number from a base64 image.

    Returns:
        int or None: The detected slide number, or None if unknown.
    """
    client, deployment = get_openai_client()

    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "What slide number is visible? Only number, or 'unknown'."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ]
        )

        content = response.choices[0].message.content.strip().lower()

        if "unknown" in content:
            return None

        digits = "".join(filter(str.isdigit, content))
        return int(digits) if digits else None

    except Exception as e:
        logging.warning(f"GPT Vision failed: {e}")
        return None
