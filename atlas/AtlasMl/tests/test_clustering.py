import numpy as np
import pytest

from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan
from atlasml.ml.Clustering.TSNE import apply_tsne


def test_tsne_output_shape_default():
    matrix = np.random.rand(100, 50)
    result = apply_tsne(matrix)
    assert result.shape == (100, 2)


def test_tsne_output_shape_custom_components():
    matrix = np.random.rand(100, 50)
    result = apply_tsne(matrix, n_components=3)
    assert result.shape == (100, 3)


def test_tsne_reproducibility():
    matrix = np.random.rand(100, 50)
    result1 = apply_tsne(matrix, random_state=42)
    result2 = apply_tsne(matrix, random_state=42)
    np.testing.assert_allclose(result1, result2, rtol=1e-5, atol=1e-5)


def test_tsne_invalid_input_type():
    with pytest.raises(Exception):
        apply_tsne("not a numpy array")


def test_tsne_perplexity_too_high():
    matrix = np.random.rand(5, 5)
    with pytest.raises(ValueError):
        apply_tsne(matrix, perplexity=50)  # too high for 5 samples


def test_hdbscan_output_shape_default():
    # Generate a dataset with 100 samples and 5 features.
    matrix = np.random.rand(100, 5)
    labels, centroid, medoid = apply_hdbscan(matrix)
    # The returned labels should be a 1D numpy array with length equal to the number of samples.
    assert isinstance(labels, np.ndarray)
    assert labels.shape[0] == 100


def test_hdbscan_invalid_input_type():
    # Passing a non-numpy array should raise an Exception.
    with pytest.raises(Exception):
        apply_hdbscan("not a numpy array")


def test_hdbscan_metric_cosine():
    # Ensure the function works with a different metric.
    matrix = np.random.rand(100, 5)
    labels = apply_hdbscan(matrix, metric="cosine")
    # Verify output shape remains consistent.
    assert isinstance(labels, np.ndarray)
    assert labels.shape[0] == 100


def test_hdbscan_noise_detection():
    # Create a simple dataset containing a tight cluster and some outliers.
    # Cluster: 50 points around (0,0)
    cluster = np.random.randn(50, 2) * 0.1
    # Outliers: 10 points far from the cluster
    noise = np.random.uniform(low=5, high=10, size=(10, 2))
    matrix = np.vstack([cluster, noise])

    # Run HDBSCAN with parameters tuned to detect noise.
    # Adjust parameters by using 'min_cluster_size' instead of 'eps' to better isolate the noise points.
    labels, centroid, medoid = apply_hdbscan(matrix, min_samples=3, min_cluster_size=15)

    # HDBSCAN typically marks noise points as -1.
    # Check that some points have been labeled as noise and provide a debug message if not.
    assert (
        -1 in labels
    ), f"Expected noise label (-1) in the output labels, but got: {np.unique(labels)}"
