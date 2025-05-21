import numpy as np
import pytest
from atlasml.ml.CompetencySimilarity import CentroidSimilarity
import atlasml.ml.CompetencySimilarity as cs_module

class DummyEmbedder:
    def __init__(self, *args, **kwargs): pass
    def __call__(self, texts):
        return [{'score': 1.0} for _ in texts]

@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr(CentroidSimilarity, 'pipeline',
                        lambda *args, **kwargs: DummyEmbedder())

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