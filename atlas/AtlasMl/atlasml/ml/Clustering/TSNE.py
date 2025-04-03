import numpy as np
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt


def apply_tsne(matrix, n_components=2, perplexity=5, random_state=42):
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
    tsne = TSNE(n_components=n_components, perplexity=perplexity, random_state=random_state)
    transformed = tsne.fit_transform(matrix)
    return transformed
