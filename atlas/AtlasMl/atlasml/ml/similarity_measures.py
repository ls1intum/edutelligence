import numpy as np
from scipy.spatial.distance import jaccard, euclidean, cosine
from typing import Union, List


def compute_jaccard_similarity(
    embedding_vector: Union[List[float], np.ndarray], 
    comparison_vector: Union[List[float], np.ndarray]
) -> float:
    """
    Computes the Jaccard similarity between two vectors.

    Args:
        embedding_vector: The input vector as a list or numpy array.
        comparison_vector: The second embedding vector to compare with.

    Returns:
        The Jaccard similarity between the two vectors (0.0 to 1.0).
        
    Raises:
        ValueError: If vectors have different dimensions.
    """
    vec1 = np.asarray(embedding_vector)
    vec2 = np.asarray(comparison_vector)

    if vec1.shape != vec2.shape:
        raise ValueError(
            f"Vector dimensions must match: {vec1.shape} vs {vec2.shape}"
        )

    jaccard_distance = jaccard(vec1, vec2)
    return 1.0 - jaccard_distance


def compute_euclidean_distance(
    embedding_vector: Union[List[float], np.ndarray], 
    comparison_vector: Union[List[float], np.ndarray]
) -> float:
    """
    Computes the Euclidean distance between two embedding vectors.

    Args:
        embedding_vector: The input vector as a list or numpy array.
        comparison_vector: The second embedding vector to compare with.

    Returns:
        The Euclidean distance between the two vectors.
        
    Raises:
        ValueError: If vectors have different dimensions.
    """
    vec1 = np.asarray(embedding_vector)
    vec2 = np.asarray(comparison_vector)

    if vec1.shape != vec2.shape:
        raise ValueError(
            f"Vector dimensions must match: {vec1.shape} vs {vec2.shape}"
        )

    return euclidean(vec1, vec2)


def compute_euclidean_similarity(
    embedding_vector: Union[List[float], np.ndarray], 
    comparison_vector: Union[List[float], np.ndarray]
) -> float:
    """
    Computes the Euclidean similarity between two embedding vectors.
    Similarity is computed as 1 / (1 + distance).

    Args:
        embedding_vector: The input vector as a list or numpy array.
        comparison_vector: The second embedding vector to compare with.

    Returns:
        The Euclidean similarity between the two vectors (0.0 to 1.0).
        
    Raises:
        ValueError: If vectors have different dimensions.
    """
    distance = compute_euclidean_distance(embedding_vector, comparison_vector)
    return 1.0 / (1.0 + distance)


def compute_cosine_similarity(
    embedding_vector: Union[List[float], np.ndarray], 
    comparison_vector: Union[List[float], np.ndarray]
) -> float:
    """
    Computes the cosine similarity between two embedding vectors.

    Args:
        embedding_vector: The input vector as a list or numpy array.
        comparison_vector: The second embedding vector to compare with.

    Returns:
        The cosine similarity between the two vectors (-1.0 to 1.0).
        
    Raises:
        ValueError: If vectors have different dimensions.
    """
    vec1 = np.asarray(embedding_vector)
    vec2 = np.asarray(comparison_vector)

    if vec1.shape != vec2.shape:
        raise ValueError(
            f"Vector dimensions must match: {vec1.shape} vs {vec2.shape}"
        )

    cosine_distance = cosine(vec1, vec2)
    return 1.0 - cosine_distance