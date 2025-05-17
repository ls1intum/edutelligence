import numpy as np
from atlasml.ml.CompetencySimilarity import CentroidSimilarity

def test_no_relations_matrix():
    embs = np.array([[1, 0],
                     [0, 1]])
    descriptions = ["foo", "bar"]

    rel = CentroidSimilarity.generate_competency_relationship(embs, descriptions)
    assert rel.tolist() == [["NONE", "NONE"],
                            ["NONE", "NONE"]]


def test_match_relations_matrix():
    embs = np.array([[1, 0],
                     [1, 0]])
    descriptions = ["same", "same"]

    rel = CentroidSimilarity.generate_competency_relationship(embs, descriptions)
    assert rel[0, 1] == "MATCH"
    assert rel[1, 0] == "MATCH"


def test_three_item_relations_matrix():
    embs = np.array([[1, 0],
                     [0, 1],
                     [1, 0]])
    descriptions = ["x", "y", "x"]

    rel = CentroidSimilarity.generate_competency_relationship(embs, descriptions)
    expected = [["NONE", "NONE", "MATCH"],
                ["NONE", "NONE", "NONE"],
                ["MATCH", "NONE", "NONE"]]
    assert rel.tolist() == expected


def test_multiple_pairs_relations_matrix():
    embs = np.array([[1, 0],
                     [1, 0],
                     [0, 1],
                     [0, 1]])
    descriptions = ["alpha", "alpha", "beta", "beta"]

    rel = CentroidSimilarity.generate_competency_relationship(embs, descriptions)
    expected = [["NONE", "MATCH", "NONE", "NONE"],
                ["MATCH", "NONE", "NONE", "NONE"],
                ["NONE", "NONE", "NONE", "MATCH"],
                ["NONE", "NONE", "MATCH", "NONE"]]
    assert rel.tolist() == expected