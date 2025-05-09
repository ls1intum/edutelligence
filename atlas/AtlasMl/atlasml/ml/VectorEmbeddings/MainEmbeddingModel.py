from openai import OpenAI

client = OpenAI()
client.api_key = "" # Replace with OpenAI API Key

response = client.embeddings.create(
    input="Task Text",
    model="text-embedding-3-small"
)

# Sanity check
print(response.data[0].embedding)