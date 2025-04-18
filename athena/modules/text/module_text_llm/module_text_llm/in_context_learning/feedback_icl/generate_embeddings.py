from langchain_openai import OpenAIEmbeddings

def embed_text(text):
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    query_result = embeddings.embed_query(text)
    return query_result
