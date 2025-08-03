from enum import Enum
import numpy as np
from typing import Tuple, Optional

from sklearn.cluster import HDBSCAN
from sklearn.manifold import TSNE


class SimilarityMetric(Enum):
    euclidean = "euclidean"
    cosine = "cosine"
    jaccard = "jaccard"


def apply_hdbscan(
    matrix: np.ndarray,
    eps: float = 0.5,
    min_samples: int = 5,
    metric: str = "euclidean",
    min_cluster_size: int = 10,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Applies HDBSCAN clustering algorithm to a given nxn matrix.

    Parameters:
        matrix (numpy.ndarray): An n x n matrix (data points x features).
        eps (float): Maximum distance between two samples for one to be considered as in the neighborhood of the other.
        min_samples (int): Minimum number of samples in a neighborhood for a point to be considered a core point.
        metric (str): The metric to use for distance computation.
        min_cluster_size (int): The minimum size of clusters.

    Returns:
        tuple: The cluster labels, centroids, and medoids assigned to each data point.
    """
    clusterer = HDBSCAN(
        min_samples=min_samples,
        metric=metric,
        store_centers="both",
        cluster_selection_epsilon=eps,
        min_cluster_size=min_cluster_size,
    )
    clusterer.fit(matrix)
    return clusterer.labels_, clusterer.centroids_, clusterer.medoids_


def apply_tsne(
    matrix: np.ndarray,
    n_components: int = 2,
    perplexity: float = 5.0,
    random_state: int = 42,
) -> np.ndarray:
    """
    Applies t-SNE to a given nxn matrix.

    Parameters:
        matrix (numpy.ndarray): An n x n matrix.
        n_components (int): Number of dimensions for the embedded space.
        perplexity (float): The perplexity parameter for TSNE.
        random_state (int): Random state for reproducibility.

    Returns:
        numpy.ndarray: The matrix after TSNE dimensionality reduction.
    """
    tsne = TSNE(
        n_components=n_components, perplexity=perplexity, random_state=random_state
    )
    transformed = tsne.fit_transform(matrix)
    return transformed
