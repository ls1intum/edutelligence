from langchain_openai import OpenAIEmbeddings

def embed_text(text):
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large")
    query_result = embeddings.embed_query(text)
    return query_result
    # return np.array(query_result, dtype=np.float32) only relevant for numpy operations
