from langchain_openai import OpenAIEmbeddings
import numpy as np
def embed_text(text):
    # Load the OpenAI API key from the environment
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    query_result = embeddings.embed_query(text)
    return np.array(query_result, dtype=np.float32)