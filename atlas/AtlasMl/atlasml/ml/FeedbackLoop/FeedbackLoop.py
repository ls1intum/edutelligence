import numpy as np

def update_cluster_centroid(
        old_centroid: np.ndarray,
        cluster_size: int,
        new_point: np.ndarray
) -> np.ndarray:
    """
    Incrementally updates a cluster centroid using the running-mean formula.

    Args:
        old_centroid (np.ndarray): Current centroid vector of shape (d,).
        cluster_size (int): Number of points currently in the cluster (before adding new_point).
        new_point (np.ndarray): The new data vector of shape (d,) to incorporate.

    Returns:
        np.ndarray: Updated centroid vector of shape (d,).

    Notes:
        - This implements μ_new = μ_old + (1/(N+1)) * (x - μ_old),
          which exactly maintains the arithmetic mean of all members
        - As cluster_size grows, the implicit α = 1/(N+1) decays, so new points have diminishing impact
    """
    alpha = 1.0 / ( cluster_size + 1)
    return old_centroid + alpha * (new_point - old_centroid)