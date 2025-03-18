import numpy as np
from scipy.spatial.distance import euclidean
from atlas.AtlasMl.atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension


def compute_euclidean_distance(embedding_vector, model: ModelDimension, comparison_vector):
    """
    Computes the Euclidean distance between two embedding vectors.

    Parameters:
        embedding_vector (iterable): The input vector.
        model (ModelDimension): An enum member indicating the dimension of the embedding_vector.
        comparison_vector (iterable): The second embedding vector to compare with.

    Returns:
        float: The Euclidean distance between the two vectors.
    """
    # Convert inputs to numpy arrays (in case they aren't already)
    vec1 = np.array(embedding_vector)
    vec2 = np.array(comparison_vector)

    # Ensure both vectors have the same shape
    if vec1.shape != vec2.shape:
        raise ValueError("Both vectors must have the same dimensions.")
    # TODO: Add vector re-shaper

    # Calculate Euclidean distance
    distance = euclidean(vec1, vec2)
    return distance