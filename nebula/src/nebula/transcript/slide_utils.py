import logging
import re

from nebula.common.config import get_openai_client
from nebula.tracing import trace_span


def ask_gpt_for_slide_number(image_b64: str, job_id: str | None = None) -> int | None:
    """
    Use GPT Vision to detect the slide number from a base64 image.

    The trace_span provides context, and LangFuse's OpenAI wrapper
    automatically traces the actual API call nested within.
    """
    model = "gpt-4.1-mini"

    with trace_span(
        "GPT Vision Slide Detection",
        metadata={"job_id": job_id, "image_length": len(image_b64)},
    ):
        try:
            if job_id:
                logging.info("[Job %s] Sending image to GPT Vision...", job_id)

            client, model_or_deployment = get_openai_client(model)

            response = client.chat.completions.create(
                model=model_or_deployment,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an AI that can read slide numbers from images of "
                            "presentation slides. "
                            "Respond only with the slide number as an integer, or 'null' "
                            "if no slide number is visible."
                            "If the image does not look like a part of a presentation "
                            "slide, respond with 'null'."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
            )

            if job_id:
                logging.info("[Job %s] GPT Vision responded", job_id)

            message_content = response.choices[0].message.content or ""
            content = message_content.strip().lower()

            if "null" in content or "unknown" in content:
                return -1  # No slide visible

            m = re.search(r"\d+", content)
            return int(m.group(0)) if m else None

        except Exception as e:
            logging.warning("GPT Vision failed: %s", e)
            return None
