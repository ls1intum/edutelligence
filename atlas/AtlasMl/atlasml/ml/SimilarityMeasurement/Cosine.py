import numpy as np
from scipy.spatial.distance import cosine
from AtlasMl.atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension


def compute_cosine_similarity(embedding_vector, model: ModelDimension, comparison_vector):
    """
    Computes the cosine similarity between two embedding vectors.

    Parameters:
        embedding_vector (iterable): The input vector.
        model (ModelDimension): An enum member indicating the dimension of the embedding_vector.
        comparison_vector (iterable): The second embedding vector to compare with.

    Returns:
        float: The cosine similarity between the two vectors.
    """
    # Convert inputs to numpy arrays (in case they aren't already)
    emb1 = np.array(embedding_vector)
    emb2 = np.array(comparison_vector)

    # Ensure both vectors have the same shape
    if emb1.shape != emb2.shape:
        raise ValueError("Both vectors must have the same dimensions.")
    # TODO: Add vector re-shaper

    # Calculate cosine similarity
    similarity = 1.0 - cosine(emb1, emb2)
    return similarity


# Sanity Check
example_vec1 = [1, 2, 3]
example_vec2 = [4, 5, 6]
computed_distance = compute_cosine_similarity(example_vec1, ModelDimension.text_embedding_three_small, example_vec2)