import pytest
import numpy as np
from unittest.mock import MagicMock, patch, call
from atlasml.ml.MLPipelines.PipelineWorkflows import PipelineWorkflows

@pytest.fixture
def workflows():
    # Patch weaviate client on instantiation
    with patch("atlasml.ml.MLPipelines.PipelineWorkflows.get_weaviate_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        wf = PipelineWorkflows()
        wf.weaviate_client = mock_client  # just in case
        yield wf

def test_initial_texts_calls_add_embeddings(workflows):
    # Arrange
    texts = ["A", "B"]
    workflows.weaviate_client.add_embeddings = MagicMock()
    with patch("atlasml.ml.MLPipelines.PipelineWorkflows.generate_embeddings_local") as mock_embed:
        mock_embed.side_effect = lambda uuid, text: (uuid, [1.0, 2.0])
        # Act
        workflows.initial_texts(texts)
    # Assert
    assert workflows.weaviate_client.add_embeddings.call_count == 2
    calls = workflows.weaviate_client.add_embeddings.call_args_list
    for c, text in zip(calls, texts):
        assert c[0][0] == "Text"
        assert c[0][2]["text"] == text

def test_initial_competencies_calls_add_embeddings(workflows):
    competencies = [
        {"title": "T1", "description": "Desc1"},
        {"title": "T2", "description": "Desc2"},
    ]
    workflows.weaviate_client.add_embeddings = MagicMock()
    with patch("atlasml.ml.MLPipelines.PipelineWorkflows.generate_embeddings_local") as mock_embed:
        mock_embed.side_effect = lambda uuid, text: (uuid, [0.5, 0.5])
        workflows.initial_competencies(competencies)
    assert workflows.weaviate_client.add_embeddings.call_count == 2
    calls = workflows.weaviate_client.add_embeddings.call_args_list
    for c, comp in zip(calls, competencies):
        assert c[0][0] == "Competency"
        assert c[0][2]["name"] == comp["title"]
        assert c[0][2]["text"] == comp["description"]

def test_initial_cluster_to_competencyPipeline(workflows):
    # Prepare some clusters and competencies in the DB
    workflows.weaviate_client.get_all_embeddings = MagicMock(side_effect=[
        [{"vector": {"default": [1.0, 0.0]}, "properties": {"cluster_id": "C1"}}],  # clusters
        [{"properties": {"competency_id": "K1", "text": "t", "name": "n"}}]         # competencies
    ])
    workflows.weaviate_client.add_embeddings = MagicMock()
    with patch("atlasml.ml.MLPipelines.PipelineWorkflows.generate_embeddings_local") as mock_embed, \
         patch("atlasml.ml.MLPipelines.PipelineWorkflows.compute_cosine_similarity") as mock_cosine:
        mock_embed.return_value = ("K1", [0.1, 0.2])
        mock_cosine.return_value = 1.0
        workflows.initial_cluster_to_competencyPipeline()
    workflows.weaviate_client.add_embeddings.assert_called_once()
    args, kwargs = workflows.weaviate_client.add_embeddings.call_args
    assert args[0] == "Competency"
    assert "cluster_id" in args[2]

def test_initial_cluster_pipeline(workflows):
    # Simulate 2 texts and 2 competencies
    workflows.weaviate_client.get_all_embeddings = MagicMock(side_effect=[
        [
            {"id": "T1", "vector": {"default": [1.0, 0.0]}, "properties": {"text_id": "T1", "text": "t1"}},
            {"id": "T2", "vector": {"default": [0.0, 1.0]}, "properties": {"text_id": "T2", "text": "t2"}},
        ],  # texts
        [   # competencies
            {"id": "K1", "vector": {"default": [0.5, 0.5]}, "properties": {"competency_id": "K1", "name": "n", "text": "desc"}}
        ],
        [   # clusters after clustering
            {"vector": {"default": [0.8, 0.2]}, "properties": {"cluster_id": "0"}}
        ]
    ])
    workflows.weaviate_client.add_embeddings = MagicMock()
    workflows.weaviate_client.update_property_by_id = MagicMock()
    workflows.weaviate_client.get_embeddings_by_property = MagicMock(return_value=[
        {"properties": {"competency_id": "K1"}}
    ])
    with patch("atlasml.ml.MLPipelines.PipelineWorkflows.apply_hdbscan") as mock_hdbscan, \
         patch("atlasml.ml.MLPipelines.PipelineWorkflows.compute_cosine_similarity") as mock_cosine:
        mock_hdbscan.return_value = ([0, 1], np.array([[0.8, 0.2]]), np.array([[0.8, 0.2]]))
        mock_cosine.return_value = 1.0
        workflows.initial_cluster_pipeline()
    assert workflows.weaviate_client.add_embeddings.call_count >= 1
    assert workflows.weaviate_client.update_property_by_id.call_count >= 1

def test_newTextPipeline(workflows):
    # Set up clusters and competencies for new text
    workflows.weaviate_client.get_all_embeddings = MagicMock(return_value=[
        {"vector": {"default": [1.0, 0.0]}, "properties": {"cluster_id": "0"}},
        {"vector": {"default": [0.0, 1.0]}, "properties": {"cluster_id": "1"}},
    ])
    workflows.weaviate_client.get_embeddings_by_property = MagicMock(return_value=[
        {"properties": {"competency_id": "K0"}}
    ])
    workflows.weaviate_client.add_embeddings = MagicMock()
    with patch("atlasml.ml.MLPipelines.PipelineWorkflows.generate_embeddings_local") as mock_embed, \
         patch("atlasml.ml.MLPipelines.PipelineWorkflows.compute_cosine_similarity") as mock_cosine:
        mock_embed.return_value = ("T123", [1.0, 0.0])
        mock_cosine.side_effect = [0.99, 0.01]
        cid = workflows.newTextPipeline("Some text", "T123")
    assert workflows.weaviate_client.add_embeddings.call_count == 1
    assert cid == "K0"