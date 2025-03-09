import numpy as np
from scipy.spatial.distance import jaccard
from AtlasMl.atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension


def compute_jaccard_similarity(embedding_vector, model: ModelDimension, comparison_vector):
    """
    Computes the Jaccard similarity between two vectors.

    Parameters:
        embedding_vector (iterable): The input vector.
        model (ModelDimension): An enum member indicating the dimension of the embedding_vector.
        comparison_vector (iterable): The second embedding vector to compare with.

    Returns:
        float: The Jaccard similarity between the two vectors.
    """
    # Convert inputs to numpy arrays
    vec1 = np.array(embedding_vector)
    vec2 = np.array(comparison_vector)

    # Ensure both vectors have the same shape
    if vec1.shape != vec2.shape:
        raise ValueError("Both vectors must have the same dimensions.")
    # TODO: Add vector re-shaper

    # Calculate Jaccard distance then convert to similarity
    distance = jaccard(vec1, vec2)
    similarity = 1.0 - distance
    return similarity


# Sanity Check
example_vec1 = [1, 2, 3]
example_vec2 = [4, 5, 6]
computed_distance = compute_jaccard_similarity(example_vec1, ModelDimension.text_embedding_three_small, example_vec2)