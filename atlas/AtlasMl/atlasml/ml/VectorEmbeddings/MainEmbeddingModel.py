from openai import OpenAI

def generate_embeddings_openai(id, description):
    client = OpenAI()
    client.api_key = ""  # Replace with OpenAI API Key
    response = client.embeddings.create(
        input=description,
        model="text-embedding-3-small"
    )
    return id, response.data[0].embedding