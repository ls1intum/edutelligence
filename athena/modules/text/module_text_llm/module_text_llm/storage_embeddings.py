import faiss
import numpy as np
import os
def save_embedding(embedding):
    # Check if the index file already exists
    if os.path.exists("embeddings.index"):
        # If it exists, load the existing index
        index = faiss.read_index("embeddings.index")
    else:
        # If not, create a new index
        index = faiss.IndexFlatL2(embedding.shape[0])  # Use the correct dimension (embedding size)

    # Add the embedding to the index
    index.add(np.array([embedding], dtype=np.float32))  # Wrap embedding in array if needed

    # Save the updated index to the disk
    faiss.write_index(index, "embeddings.index")

def query_embedding(query_embedding):
    # Check if the index file exists
    index_file = 'embeddings.index'
    
    if not os.path.exists(index_file):
        print(f"Error: The index file '{index_file}' does not exist.")
        return None
    
    try:
        # Read the FAISS index
        index = faiss.read_index(index_file)
    except Exception as e:
        print(f"Error while reading the FAISS index: {e}")
        return None

    # Ensure the query_embedding is in the correct shape
    try:
        query_embedding = np.array([query_embedding], dtype=np.float32)  # Convert to np array
        if query_embedding.ndim != 2 or query_embedding.shape[1] != index.d:  # Check the dimension compatibility
            print(f"Error: Query embedding shape does not match the index dimensions.")
            return None
    except Exception as e:
        print(f"Error with embedding format: {e}")
        return None
    
    # Set the number of nearest neighbors to retrieve
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
