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
        - As cluster_size grows, the implicit α = 1/(N+1) decays, so new points have a diminishing impact
    """
    alpha = 1.0 / ( float(cluster_size) + 1.0)
    return old_centroid + alpha * (new_point - old_centroid)

def update_cluster_centroid_on_removal(
    old_centroid: np.ndarray,
    cluster_size: int,
    removed_point: np.ndarray
) -> np.ndarray:
    """
    Updates a cluster centroid when a point is removed.

    Args:
        old_centroid (np.ndarray): Current centroid vector of shape (d,).
        cluster_size (int): Number of points currently in the cluster (before removing removed_point).
        removed_point (np.ndarray): The data vector of shape (d,) that is being removed.

    Returns:
        np.ndarray: Updated centroid vector of shape (d,).

    Raises:
        ValueError: If cluster_size <= 1 (cannot define a centroid after removal),
                    or if shapes do not match.

    Notes:
        - Implements μ_new = (N * μ_old - x_removed) / (N - 1)
        - This exactly maintains the arithmetic mean of the remaining members
        - If cluster_size == 1, removing the only point leaves an empty cluster,
          so the centroid is undefined (raise ValueError).
    """
    if cluster_size <= 1:
        raise ValueError("Cannot update centroid on removal when cluster_size <= 1 (centroid undefined).")

    old_centroid = np.asarray(old_centroid)
    removed_point = np.asarray(removed_point)

    if old_centroid.shape != removed_point.shape:
        raise ValueError(f"Vector dimensions must match: {old_centroid.shape} vs {removed_point.shape}")

    n = float(cluster_size)
    return (n * old_centroid - removed_point) / (n - 1.0)
