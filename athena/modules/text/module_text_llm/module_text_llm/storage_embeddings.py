import faiss
import numpy as np
import os
def save_embedding(embedding, exercise_id):
    if os.path.exists(f"embeddings_{exercise_id}.index"):
        index = faiss.read_index(f"embeddings_{exercise_id}.index")
    else:
        index = faiss.IndexFlatL2(embedding.shape[0])

    index.add(np.array([embedding], dtype=np.float32))
    faiss.write_index(index, f"embeddings_{exercise_id}.index")

def query_embedding(query_embedding,exercise_id):
    index_file = f'embeddings_{exercise_id}.index'
    
    if not os.path.exists(index_file):
        print(f"Error: The index file '{index_file}' does not exist.")
        return None
    
    try:
        index = faiss.read_index(index_file)
    except Exception as e:
        print(f"Error while reading the FAISS index: {e}")
        return None

    try:
        query_embedding = np.array([query_embedding], dtype=np.float32) 
        if query_embedding.ndim != 2 or query_embedding.shape[1] != index.d:
            print("Error: Query embedding shape does not match the index dimensions.")
            return None
    except Exception as e:
        print(f"Error with embedding format: {e}")
        return None
    
    k = 3  # Number of nearest neighbors

    try:
        # Search the index for nearest neighbors
        distances, indices = index.search(query_embedding, k)
        print(f"Indices of similar texts: {indices}")
        print(f"Distances: {distances}")
        return indices
    except Exception as e:
        print(f"Error during FAISS search: {e}")
        return None
