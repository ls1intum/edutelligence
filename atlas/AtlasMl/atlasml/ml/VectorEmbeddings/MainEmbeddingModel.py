import os
from dotenv import load_dotenv
load_dotenv()
from openai import AzureOpenAI, OpenAIError


def generate_embeddings_openai(id, description: str):
    client = AzureOpenAI(
        api_key=os.environ.get("OPENAI_API_KEY"),
        azure_endpoint=os.environ.get("OPENAI_API_URL"),
        api_version="2023-05-15",
    )
    # Send embedding request
    response = client.embeddings.create(
        model="te-3-small",
        input=description,
    )
    return id, response.data[0].embedding
