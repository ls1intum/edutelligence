from nebula.llm.openai_client import get_openai_client

def rewrite_faq_text(input_text: str) -> str:
    client, deployment = get_openai_client("azure-gpt-4-omni")

    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": "You are a helpful assistant that rewrites FAQ input clearly and concisely."},
            {"role": "user", "content": input_text},
        ],
    )

    return response.choices[0].message.content.strip()
