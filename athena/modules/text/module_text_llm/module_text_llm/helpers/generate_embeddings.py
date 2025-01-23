from langchain_openai import OpenAIEmbeddings
import numpy as np
import os

def embed_text(text):
    """
    Generate an embedding for a given text using OpenAI's embedding model.
    """
    embeddings = OpenAIEmbeddings(model="text-embedding-ada-002")
    query_result = embeddings.embed_query(text)
    return np.array(query_result, dtype=np.float32)


def save_embeddings_to_file(embeddings, filename="keyword_embeddings.npy"):
    """
    Save embeddings to a .npy file.
    Parameters:
        embeddings (np.ndarray): The embeddings to save.
        filename (str): The filename where embeddings will be saved.
    """
    np.save(filename, embeddings)
    print(f"Embeddings saved to {filename}")


def load_embeddings_from_file(filename="keyword_embeddings.npy"):
    """
    Load embeddings from a .npy file.
    Parameters:
        filename (str): The filename from which embeddings will be loaded.
    Returns:
        np.ndarray: The loaded embeddings.
    """
    if os.path.exists(filename):
        embeddings = np.load(filename)
        print(f"Embeddings loaded from {filename}")
        return embeddings

    print(f"{filename} does not exist.")
    return None