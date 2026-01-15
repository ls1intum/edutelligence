import logging
import re

from nebula.common.config import get_openai_client
from nebula.tracing import trace_generation


def ask_gpt_for_slide_number(image_b64: str, job_id: str | None = None) -> int | None:
    """
    Use GPT Vision to detect the slide number from a base64 image.
    """
    model = "gpt-4.1-mini"

    with trace_generation(
        name="GPT Vision Slide Detection",
        model=model,
        input_data={"image_length": len(image_b64)},
        metadata={"job_id": job_id} if job_id else {},
    ) as gen:
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

            # Extract usage if available
            usage = None
            if hasattr(response, "usage") and response.usage:
                usage = {
                    "input": response.usage.prompt_tokens,
                    "output": response.usage.completion_tokens,
                }

            content = message_content.strip().lower()
            if "null" in content or "unknown" in content:
                gen.end(output={"result": "no_slide", "raw": content[:50]}, usage=usage)
                return -1  # No slide visible

            m = re.search(r"\d+", content)
            result = int(m.group(0)) if m else None
            gen.end(output={"result": result, "raw": content[:50]}, usage=usage)
            return result

        except Exception as e:
            gen.end(error=str(e))
            logging.warning("GPT Vision failed: %s", e)
            return None
