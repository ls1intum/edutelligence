from langchain_openai import OpenAIEmbeddings
import numpy as np
from module_text_llm import embedding_model

def embed_text(text):
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    query_result = embeddings.embed_query(text)
    return np.array(query_result, dtype=np.float32)

def embed_bert(text):
    return embedding_model.encode(text)