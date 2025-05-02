import logging
from llm_utils import get_openai_client

def ask_gpt_for_slide_number(image_b64):
    client, deployment = get_openai_client()
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What slide number is visible? Only number, or 'unknown'."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "high"  # <- important!
                            }
                        }
                    ]
                }
            ]
        )
        content = response.choices[0].message.content.strip().lower()
        if "unknown" in content:
            return None
        return int("".join(filter(str.isdigit, content)))
    except Exception as e:
        logging.warning(f"GPT Vision failed: {e}")
        return None