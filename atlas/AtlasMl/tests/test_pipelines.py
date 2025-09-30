import pytest
import uuid
from atlasml.clients.weaviate import CollectionNames
from atlasml.ml.pipeline_workflows import PipelineWorkflows
from atlasml.models.competency import ExerciseWithCompetencies, Competency
from unittest.mock import patch, MagicMock
import numpy as np


@pytest.fixture
def workflows(mock_weaviate_client):
    """Create PipelineWorkflows using MockWeaviateClient from conftest.py"""
    with patch("atlasml.ml.pipeline_workflows.get_weaviate_client", return_value=mock_weaviate_client):
        wf = PipelineWorkflows(weaviate_client=mock_weaviate_client)
        yield wf


def test_initial_texts_integration(workflows):
    texts = [
        ExerciseWithCompetencies(
            id=i + 1,
            title="Integration Exercise",
            description="Integration Exercise Description",
            competencies=[],
            course_id=1,
        )
        for i in range(2)
    ]
    workflows.initial_exercises(texts)
    inserted = workflows.weaviate_client.get_all_embeddings("Exercise")
    found_texts = [item["properties"]["description"] for item in inserted]
    for t in texts:
        assert any(t.description == ft for ft in found_texts)


def test_initial_competencies_integration(workflows):
    competencies = [
        Competency(
            id=i + 1,
            title="Integration Competency",
            description="Description",
            course_id=1,
        )
        for i in range(2)
    ]
    workflows.initial_competencies(competencies)
    inserted = workflows.weaviate_client.get_all_embeddings("Competency")
    found_titles = [item["properties"]["title"] for item in inserted]
    for comp in competencies:
        assert any(comp.title == ft for ft in found_titles)


def fake_hdbscan(embeddings_list, *args, **kwargs):
    n = len(embeddings_list)
    # Assign all points to cluster 0
    labels = [0] * n
    centroids = [np.array([0.1, 0.2, 0.3])]
    medoids = [np.array([0.1, 0.2, 0.3])]
    return labels, centroids, medoids


def test_newTextPipeline_integration(workflows):
    with patch("atlasml.ml.pipeline_workflows.apply_hdbscan", side_effect=fake_hdbscan):
        competencies = [
            Competency(
                id=7,
                title="Data Structures Mastery",
                description="Ability to understand and efficiently use core data structures such as lists, arrays, dictionaries, tuples, and sets. This includes selecting the appropriate structure for a task and applying common operations like searching, sorting, and modifying data.",
                course_id=1,
            ),
            Competency(
                id=8,
                title="Programming Fundamentals",
                description="Proficiency in core programming concepts, including variables, loops, and functions. Capable of writing, reading, and debugging code that uses these basic elements to implement algorithms and solve problems.",
                course_id=1,
            ),
            Competency(
                id=9,
                title="Object-Oriented and Algorithmic Thinking",
                description="Understanding of object-oriented programming concepts such as classes and recursion, and their role in organizing code and solving complex problems. Can design class hierarchies, use recursion effectively, and apply these patterns to real-world scenarios.",
                course_id=1,
            ),
        ]
        workflows.initial_competencies(competencies)
        workflows.weaviate_client.add_embeddings(
            "Competency",
            [0.1, 0.2, 0.3],  # match your embedding size
            {
                "competency_id": 10,
                "title": "Fake Competency",
                "description": "Fake Competency Description",
                "cluster_id": "fake-cluster-id",
                "cluster_similarity_score": 0.9,
                "course_id": "1"
            },
        )
        titles = [
            "Lists",
            "Arrays",
            "Variables",
            "Dictionaries",
            "Functions",
            "Loops",
            "Tuples",
            "Sets",
            "Classes",
            "Recursion",
        ]
        texts = [
            ExerciseWithCompetencies(
                id=i + 10,
                title=title,
                description=title,
                competencies=[],
                course_id=1,
            )
            for i, title in enumerate(titles)
        ]
        workflows.initial_exercises(texts)
        # Ensure at least one cluster exists for downstream code
        fake_cluster_id = workflows.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)[3]["properties"]["cluster_id"]
        workflows.weaviate_client.add_embeddings(
            "SemanticCluster",
            [0.1, 0.2, 0.3],  # match your embedding size
            {"cluster_id": fake_cluster_id, "course_id": "1"},
        )
        test_text = "object-oriented programming"
        competency = workflows.new_text_suggestion(test_text, course_id=1)
        assert competency, "Competency ID not found!"


def test_suggest_competency_relations_integration(workflows):
    """Test the suggest_competency_relations pipeline method"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        # Setup test competencies
        competencies = [
            Competency(
                id=10,
                title="Python Programming",
                description="Basic Python programming skills including variables, loops, and functions",
                course_id=1,
            ),
            Competency(
                id=11,
                title="Data Structures",
                description="Understanding of lists, dictionaries, sets and their applications",
                course_id=1,
            ),
            Competency(
                id=12,
                title="Algorithm Design",
                description="Ability to design and analyze algorithms for problem solving",
                course_id=1,
            )
        ]
        # Add competencies to workflows
        workflows.initial_competencies(competencies)
        # Mock the relationship generation to return a predictable matrix
        # 3x3 matrix with different relation types
        mock_relationship_matrix = np.array([
            ["NONE", "REQUIRES", "EXTENDS"],
            ["MATCH", "NONE", "REQUIRES"],
            ["NONE", "EXTENDS", "NONE"]
        ])
        mock_generate.return_value = mock_relationship_matrix
        # Test the suggest_competency_relations method
        result = workflows.suggest_competency_relations(course_id=1)
        # Verify the result structure
        assert hasattr(result, 'relations'), "Result should have relations attribute"
        assert isinstance(result.relations, list), "Relations should be a list"
        # Should have 5 relations (excluding NONE diagonal and NONE entries)
        # REQUIRES: (0,1), EXTENDS: (0,2), MATCH: (1,0), REQUIRES: (1,2), EXTENDS: (2,1)
        assert len(result.relations) == 5, f"Expected 5 relations, got {len(result.relations)}"
        # Verify specific relations
        relation_dict = {
            (r.tail_id, r.head_id): r.relation_type.value
            for r in result.relations
        }
        # Check expected relations based on our mock matrix
        expected_relations = {
            ("10", "11"): "REQUIRES",  # competency 10 -> 11
            ("10", "12"): "EXTENDS",  # competency 10 -> 12
            ("11", "10"): "MATCH",  # competency 11 -> 10
            ("11", "12"): "REQUIRES",  # competency 11 -> 12
            ("12", "11"): "EXTENDS",  # competency 12 -> 11
        }
        for (tail, head), expected_type in expected_relations.items():
            assert (tail, head) in relation_dict, f"Missing relation {tail} -> {head}"
            assert relation_dict[(tail, head)] == expected_type, \
                f"Expected {expected_type} for {tail}->{head}, got {relation_dict[(tail, head)]}"
        # Verify generate_competency_relationship was called correctly
        mock_generate.assert_called_once()
        call_args = mock_generate.call_args
        embeddings_arg = call_args[0][0]  # First positional argument
        descriptions_arg = call_args[1]  # Second positional argument
        # Should be called with 3 embeddings and 3 descriptions
        assert len(embeddings_arg) == 3, "Should pass 3 embeddings"
        assert len(descriptions_arg) == 3, "Should pass 3 descriptions"


def test_suggest_competency_relations_empty_course(workflows):
    """Test suggest_competency_relations with no competencies"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        # Test with non-existent course_id
        result = workflows.suggest_competency_relations(course_id=999)
        # Should return empty relations
        assert hasattr(result, 'relations'), "Result should have relations attribute"
        assert isinstance(result.relations, list), "Relations should be a list"
        assert len(result.relations) == 0, "Should return empty relations for non-existent course"
        # generate_competency_relationship should not be called
        mock_generate.assert_not_called()


def test_suggest_competency_relations_single_competency(workflows):
    """Test suggest_competency_relations with only one competency"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        # Setup single competency
        single_competency = [
            Competency(
                id=20,
                title="Single Competency",
                description="The only competency in this course",
                course_id=2,
            )
        ]
        workflows.initial_competencies(single_competency)
        # Mock should return 1x1 matrix with NONE
        mock_generate.return_value = np.array([["NONE"]])
        result = workflows.suggest_competency_relations(course_id=2)
        # Should return empty relations (no relations for single competency)
        assert len(result.relations) == 0, "Single competency should result in no relations"
        # generate_competency_relationship should still be called
        mock_generate.assert_called_once()


def test_suggest_competency_relations_two_competencies(workflows):
    """Test suggest_competency_relations with exactly two competencies"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        # Setup two competencies
        two_competencies = [
            Competency(
                id=30,
                title="First Competency",
                description="First competency description",
                course_id=3,
            ),
            Competency(
                id=31,
                title="Second Competency",
                description="Second competency description",
                course_id=3,
            )
        ]
        workflows.initial_competencies(two_competencies)
        # Mock 2x2 matrix
        mock_generate.return_value = np.array([
            ["NONE", "REQUIRES"],
            ["EXTENDS", "NONE"]
        ])
        result = workflows.suggest_competency_relations(course_id="3")
        # Should have 2 relations
        assert len(result.relations) == 2, f"Expected 2 relations, got {len(result.relations)}"
        # Verify the specific relations
        relation_types = [(r.tail_id, r.head_id, r.relation_type.value) for r in result.relations]
        expected = [("30", "31", "REQUIRES"), ("31", "30", "EXTENDS")]
        for expected_relation in expected:
            assert expected_relation in relation_types, f"Missing expected relation: {expected_relation}"


def test_suggest_competency_relations_all_none_matrix(workflows):
    """Test suggest_competency_relations when all relations are NONE"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        # Setup competencies
        competencies = [
            Competency(
                id=40,
                title="Independent Competency 1",
                description="First independent competency",
                course_id=4,
            ),
            Competency(
                id=41,
                title="Independent Competency 2",
                description="Second independent competency",
                course_id=4,
            )
        ]
        workflows.initial_competencies(competencies)
        # Mock matrix with all NONE values
        mock_generate.return_value = np.array([
            ["NONE", "NONE"],
            ["NONE", "NONE"]
        ])
        result = workflows.suggest_competency_relations(course_id="4")
        # Should return empty relations (all NONE filtered out)
        assert len(result.relations) == 0, "All NONE relations should result in empty list"


def test_suggest_competency_relations_large_course(workflows):
    """Test suggest_competency_relations with many competencies"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        # Setup 5 competencies
        many_competencies = [
            Competency(
                id=50 + i,
                title=f"Competency {i + 1}",
                description=f"Description for competency {i + 1}",
                course_id=5,
            )
            for i in range(5)
        ]
        workflows.initial_competencies(many_competencies)
        # Create a 5x5 matrix with some relations
        matrix = np.full((5, 5), "NONE", dtype=object)
        matrix[0, 1] = "REQUIRES"
        matrix[1, 2] = "EXTENDS"
        matrix[2, 3] = "MATCH"
        matrix[3, 4] = "REQUIRES"
        matrix[4, 0] = "EXTENDS"
        mock_generate.return_value = matrix
        result = workflows.suggest_competency_relations(course_id="5")
        # Should have 5 non-NONE relations
        assert len(result.relations) == 5, f"Expected 5 relations, got {len(result.relations)}"
        # Verify all relation types are represented
        relation_types = {r.relation_type.value for r in result.relations}
        expected_types = {"REQUIRES", "EXTENDS", "MATCH"}
        assert relation_types == expected_types, f"Expected {expected_types}, got {relation_types}"


# ============================================================================
# New mapping tests - using MockWeaviateClient from conftest.py
# ============================================================================

def test_map_new_competency_to_exercise_success(workflows, mock_weaviate_client):
    """Test successful mapping with complete mock data"""
    # Setup: Add exercise with all required fields
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 1,
            "title": "Test Exercise",
            "description": "Test Description",
            "competency_ids": [],
            "course_id": 1,
        }
    )
    
    # Setup: Add competency with all required fields
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Test Competency",
            "description": "Test Competency Description",
            "course_id": 1,
        }
    )
    
    # Spy on update to verify it's called correctly
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_new_competency_to_exercise(exercise_id=1, competency_id=2)
        
        # Assert: Verify update was called
        spy.assert_called_once()
        call_args = spy.call_args[0]
        assert call_args[0] == CollectionNames.EXERCISE.value
        # Verify competency 2 was added to the list
        assert 2 in call_args[2]["competency_ids"]


def test_map_new_competency_to_exercise_duplicate_prevention(workflows, mock_weaviate_client):
    """Test that duplicate mappings are prevented"""
    # Setup: Exercise already has competency 2
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 1,
            "title": "Test Exercise",
            "description": "Test Description",
            "competency_ids": [2],  # Already has competency 2
            "course_id": 1,
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Test Competency",
            "description": "Test Competency Description",
            "course_id": 1,
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_new_competency_to_exercise(exercise_id=1, competency_id=2)
        
        # Assert: update should NOT be called since it's already mapped
        spy.assert_not_called()


def test_map_new_competency_to_exercise_nonexistent_raises_error(workflows, mock_weaviate_client):
    """Test mapping to nonexistent exercise/competency raises ValueError"""
    # No data added - both are nonexistent
    
    with pytest.raises(ValueError):
        workflows.map_new_competency_to_exercise(exercise_id=999, competency_id=999)


def test_map_new_competency_to_exercise_handles_none_competencies(workflows, mock_weaviate_client):
    """Test handling of None/missing competency_ids"""
    # Setup: Exercise with None competency_ids
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 1,
            "title": "Test Exercise",
            "description": "Test Description",
            "competency_ids": None,  # None value
            "course_id": 1,
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Test Competency",
            "description": "Test Competency Description",
            "course_id": 1,
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act: Should handle None gracefully
        workflows.map_new_competency_to_exercise(exercise_id=1, competency_id=2)
        
        # Assert: Should successfully add competency
        spy.assert_called_once()
        call_args = spy.call_args[0]
        assert 2 in call_args[2]["competency_ids"]


def test_map_competency_to_competency_bidirectional(workflows, mock_weaviate_client):
    """Test bidirectional relationship creation"""
    # Setup: Two competencies with all required fields
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 1,
            "title": "Competency 1",
            "description": "Description 1",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Competency 2",
            "description": "Description 2",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)
        
        # Assert: Should call update twice (bidirectional)
        assert spy.call_count == 2
        
        # Verify both updates include the relationship
        calls = spy.call_args_list
        # Check source was updated with target
        source_updated = any(2 in call[0][2].get("related_competencies", []) for call in calls)
        # Check target was updated with source
        target_updated = any(1 in call[0][2].get("related_competencies", []) for call in calls)
        assert source_updated and target_updated, "Both directions should be updated"


def test_map_competency_to_competency_preserves_existing(workflows, mock_weaviate_client):
    """Test that existing relations are preserved"""
    # Setup: Competency 1 already related to 3
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 1,
            "title": "Competency 1",
            "description": "Description 1",
            "course_id": 1,
            "related_competencies": [3],  # Existing relation
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Competency 2",
            "description": "Description 2",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)
        
        # Assert: Check that source update includes both 3 and 2
        spy.assert_called()
        calls = spy.call_args_list
        source_call = [c for c in calls if "related_competencies" in c[0][2] 
                       and (3 in c[0][2]["related_competencies"] or 2 in c[0][2]["related_competencies"])]
        assert len(source_call) > 0, "Source should be updated"
        # Verify both relations exist
        source_relations = [c[0][2]["related_competencies"] for c in source_call if 3 in c[0][2]["related_competencies"]]
        if source_relations:
            assert 2 in source_relations[0], "Should preserve existing relation and add new one"


def test_map_competency_to_competency_duplicate_prevention(workflows, mock_weaviate_client):
    """Test that duplicate relationships are not created"""
    # Setup: Competencies already related
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 1,
            "title": "Competency 1",
            "description": "Description 1",
            "course_id": 1,
            "related_competencies": [2],  # Already related
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Competency 2",
            "description": "Description 2",
            "course_id": 1,
            "related_competencies": [1],  # Already related
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)
        
        # Assert: Should NOT call update since already mapped
        spy.assert_not_called()


def test_map_competency_to_competency_nonexistent_source(workflows, mock_weaviate_client):
    """Test mapping from nonexistent source raises ValueError"""
    # Setup: Only add target
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Competency 2",
            "description": "Description 2",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with pytest.raises(ValueError):
        workflows.map_competency_to_competency(source_competency_id=999, target_competency_id=2)


def test_map_competency_to_competency_nonexistent_target(workflows, mock_weaviate_client):
    """Test mapping to nonexistent target raises ValueError"""
    # Setup: Only add source
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 1,
            "title": "Competency 1",
            "description": "Description 1",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with pytest.raises(ValueError):
        workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=999)


def test_map_competency_to_competency_handles_none_relations(workflows, mock_weaviate_client):
    """Test handling of None/missing related_competencies"""
    # Setup: One with None, one missing the field
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 1,
            "title": "Competency 1",
            "description": "Description 1",
            "course_id": 1,
            "related_competencies": None,  # None value
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 2,
            "title": "Competency 2",
            "description": "Description 2",
            "course_id": 1,
            # Missing related_competencies field
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act: Should handle None/missing gracefully
        workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)
        
        # Assert: Should successfully create relationship
        assert spy.call_count == 2, "Should update both competencies"
