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