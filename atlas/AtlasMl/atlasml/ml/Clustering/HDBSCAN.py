import numpy as np
from sklearn.cluster import HDBSCAN
from enum import Enum

class SimilarityMetric(Enum):
    euclidean = 'euclidean'
    cosine = 'cosine'
    jaccard = 'jaccard'


def apply_hdbscan(matrix, eps=0.5, min_samples=5, metric='euclidean',  min_cluster_size=10):
    """
    Applies HDBSCAN clustering algorithm to a given nxn matrix.

    Parameters:
        matrix (numpy.ndarray): An n x n matrix (data points x features).
        eps (float): Maximum distance between two samples for one to be considered as in the neighborhood of the other.
        min_samples (int): Minimum number of samples in a neighborhood for a point to be considered a core point.
        metric (str): The metric to use for distance computation.

    Returns:
        numpy.ndarray: The cluster labels assigned to each data point.
    """
    clusterer = HDBSCAN(min_samples=min_samples, metric=metric, cluster_selection_epsilon=eps, min_cluster_size=min_cluster_size)
    clusterer.fit(matrix)
    return clusterer.labels_
