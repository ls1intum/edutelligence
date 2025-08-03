import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from atlasml.ml.generate_competency_relationship import generate_competency_relationship


def test_identical_embeddings_with_high_entailment_returns_match():
    """Test that identical embeddings with high mutual entailment return MATCH."""
    embeddings = np.array([[1.0, 0.0], [1.0, 0.0]])
    descriptions = ["Learn programming", "Learn programming"]
    
    # Mock the pipeline to return high entailment scores
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = {"scores": [0.9]}  # High entailment
    
    with patch('atlasml.ml.generate_competency_relationship.pipeline', return_value=mock_pipeline):
        result = generate_competency_relationship(embeddings, descriptions)
    
    assert result[0, 1] == "MATCH"
    assert result[1, 0] == "MATCH"


def test_orthogonal_embeddings_returns_none():
    """Test that orthogonal embeddings return NONE relationship."""
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
    descriptions = ["Learn programming", "Learn cooking"]
    
    # Mock the pipeline - doesn't matter much since cosine similarity is too low
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = {"scores": [0.5]}
    
    with patch('atlasml.ml.generate_competency_relationship.pipeline', return_value=mock_pipeline):
        result = generate_competency_relationship(embeddings, descriptions)
    
    assert result[0, 1] == "NONE"
    assert result[1, 0] == "NONE"


def test_high_similarity_with_directional_entailment_returns_require():
    """Test that high similarity with directional entailment returns REQUIRE."""
    embeddings = np.array([[1.0, 0.0], [0.9, 0.1]])  # High similarity
    descriptions = ["Basic programming", "Advanced programming"]
    
    # Mock the pipeline to return directional entailment
    mock_pipeline = MagicMock()
    def mock_call(text, candidate_labels):
        if "Basic" in text and "Advanced" in candidate_labels[0]:
            return {"scores": [0.85]}  # Basic -> Advanced: high entailment
        elif "Advanced" in text and "Basic" in candidate_labels[0]:
            return {"scores": [0.3]}   # Advanced -> Basic: low entailment
        return {"scores": [0.5]}
    
    mock_pipeline.side_effect = mock_call
    
    with patch('atlasml.ml.generate_competency_relationship.pipeline', return_value=mock_pipeline):
        result = generate_competency_relationship(embeddings, descriptions)
    
    assert result[0, 1] == "REQUIRE"  # Basic requires Advanced
    assert result[1, 0] == "EXTEND"   # Advanced extends Basic


def test_high_similarity_with_reverse_directional_entailment_returns_extend():
    """Test that high similarity with reverse directional entailment returns EXTEND."""
    embeddings = np.array([[1.0, 0.0], [0.9, 0.1]])  # High similarity
    descriptions = ["Advanced programming", "Basic programming"]
    
    # Mock the pipeline to return reverse directional entailment
    mock_pipeline = MagicMock()
    def mock_call(text, candidate_labels):
        if "Advanced" in text and "Basic" in candidate_labels[0]:
            return {"scores": [0.3]}   # Advanced -> Basic: low entailment
        elif "Basic" in text and "Advanced" in candidate_labels[0]:
            return {"scores": [0.85]}  # Basic -> Advanced: high entailment
        return {"scores": [0.5]}
    
    mock_pipeline.side_effect = mock_call
    
    with patch('atlasml.ml.generate_competency_relationship.pipeline', return_value=mock_pipeline):
        result = generate_competency_relationship(embeddings, descriptions)
    
    assert result[0, 1] == "EXTEND"   # Advanced extends Basic
    assert result[1, 0] == "REQUIRE"  # Basic requires Advanced


def test_high_similarity_with_low_entailment_returns_none():
    """Test that high similarity with low mutual entailment returns NONE."""
    embeddings = np.array([[1.0, 0.0], [0.8, 0.2]])  # Moderate similarity
    descriptions = ["Programming in Python", "Programming in Java"]
    
    # Mock the pipeline to return low entailment scores
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = {"scores": [0.4]}  # Low entailment
    
    with patch('atlasml.ml.generate_competency_relationship.pipeline', return_value=mock_pipeline):
        result = generate_competency_relationship(embeddings, descriptions)
    
    assert result[0, 1] == "NONE"
    assert result[1, 0] == "NONE"


def test_diagonal_elements_are_none():
    """Test that diagonal elements (self-relationships) are NONE."""
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
    descriptions = ["Learn programming", "Learn cooking"]
    
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = {"scores": [0.9]}
    
    with patch('atlasml.ml.generate_competency_relationship.pipeline', return_value=mock_pipeline):
        result = generate_competency_relationship(embeddings, descriptions)
    
    assert result[0, 0] == "NONE"
    assert result[1, 1] == "NONE"


def test_matrix_shape_matches_input():
    """Test that output matrix shape matches input embeddings."""
    n_competencies = 5
    embeddings = np.random.rand(n_competencies, 3)
    descriptions = [f"Competency {i}" for i in range(n_competencies)]
    
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = {"scores": [0.5]}
    
    with patch('atlasml.ml.generate_competency_relationship.pipeline', return_value=mock_pipeline):
        result = generate_competency_relationship(embeddings, descriptions)
    
    assert result.shape == (n_competencies, n_competencies)
    assert result.dtype == object