from langchain_openai import OpenAIEmbeddings
import numpy as np
from module_text_llm import embedding_model
from athena.logger import logger
def embed_text(text):
    # Load the OpenAI API key from the environment
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    query_result = embeddings.embed_query(text)
    return np.array(query_result, dtype=np.float32)

def embed_bert(text):
    return embedding_model.encode(text)

# def embed_text_batch(texts):
#     # Load the OpenAI API key from the environment
#     embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
#     query_result = embeddings.embed_query_batch(texts)
#     return np.array(query_result, dtype=np.float32)