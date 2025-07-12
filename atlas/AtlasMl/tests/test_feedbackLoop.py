import numpy as np
import pytest
from atlasml.ml.FeedbackLoop.FeedbackLoop import update_cluster_centroid


def test_when_cluster_is_empty_return_new_point():
    """
    If cluster_size=0, then the “old centroid” is effectively unused,
    and the updated centroid should equal the new_point exactly.
    """
    old_centroid = np.array([0.5, -1.2, 3.3])
    new_point   = np.array([1.0,  2.0, -3.0])
    updated = update_cluster_centroid(old_centroid, cluster_size=0, new_point=new_point)
    # Expectation: when N=0, alpha = 1/(0+1)=1, so μ_new = μ_old + 1*(x - μ_old) = x
    assert np.allclose(updated, new_point), f"Got {updated}, expected {new_point}"


def test_single_increment_from_zero_centroid():
    """
    If the old centroid is [0, 0, 0] and cluster_size=1,
    then μ_new = (1*old + x)/(1+1) = x/2.
    """
    old_centroid = np.zeros(3)
    new_point   = np.array([2.0,  4.0, -6.0])
    updated = update_cluster_centroid(old_centroid, cluster_size=1, new_point=new_point)
    expected = new_point / 2.0  # [1.0, 2.0, -3.0]
    assert np.allclose(updated, expected), f"Got {updated}, expected {expected}"


def test_two_sequential_updates_yield_running_mean():
    """
    Simulate adding two points one by one. We start with an initial centroid,
    then add p1, then add p2; after both insertions, the final centroid
    should be the arithmetic mean of (initially empty cluster + p1 + p2).
    """
    # 1) Start with cluster of size 0; first insertion should just return p1.
    p1 = np.array([1.0, 1.0, 1.0])
    cen = np.array([10.0, 10.0, 10.0])  # this value is irrelevant when cluster_size=0
    cen = update_cluster_centroid(cen, cluster_size=0, new_point=p1)
    assert np.allclose(cen, p1), f"Step1: Got {cen}, expected {p1}"

    # 2) Now cluster_size=1, add p2. The new centroid should be (p1 + p2)/(1+1).
    p2 = np.array([3.0, 5.0, 7.0])
    cen2 = update_cluster_centroid(old_centroid=cen, cluster_size=1, new_point=p2)
    expected2 = (p1 + p2) / 2.0
    assert np.allclose(cen2, expected2), f"Step2: Got {cen2}, expected {expected2}"


@pytest.mark.parametrize("old_centroid, size, new_point, expected", [
    # Adding to a cluster of size 2: α = 1/3
    (np.array([0.0, 0.0]), 2, np.array([3.0, 3.0]), (2/3)*np.array([0.0, 0.0]) + (1/3)*np.array([3.0, 3.0])),
    # Adding to a cluster of size 3: α = 1/4
    (np.array([1.0, 2.0]), 3, np.array([5.0, 7.0]), (3/4)*np.array([1.0, 2.0]) + (1/4)*np.array([5.0, 7.0])),
    # Higher dimension case: size=5
    (
        np.array([1.0, 1.0, 1.0, 1.0]),
        5,
        np.array([2.0, 4.0, -1.0, 0.0]),
        (5/6)*np.array([1.0, 1.0, 1.0, 1.0]) + (1/6)*np.array([2.0, 4.0, -1.0, 0.0])
    ),
])
def test_parametrized_running_mean(old_centroid, size, new_point, expected):
    """
    Verify that for various sizes and dimensions,
    update_cluster_centroid produces the weighted running mean:
      μ_new = μ_old + (1/(size+1))*(new_point - μ_old)
    which is algebraically (size*μ_old + new_point)/(size+1).
    """
    updated = update_cluster_centroid(old_centroid, cluster_size=size, new_point=new_point)
    assert np.allclose(updated, expected), f"For size={size}, got {updated}, expected {expected}"


def test_non_mutation_of_inputs():
    """
    Ensure that the function does not modify the original arrays in-place.
    """
    old = np.array([0.0, 0.0, 0.0])
    p = np.array([3.0, 3.0, 3.0])

    old_copy = old.copy()
    p_copy   = p.copy()

    _ = update_cluster_centroid(old, cluster_size=2, new_point=p)

    # After calling, the originals should remain unchanged
    assert np.allclose(old, old_copy), f"Old centroid was modified: {old} vs {old_copy}"
    assert np.allclose(p,   p_copy),   f"New point was modified: {p} vs {p_copy}"