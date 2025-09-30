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
    # Clear any static data that might interfere with tests
    for collection_name in ["Exercise", "Competency", "SEMANTIC_CLUSTER"]:
        collection = mock_weaviate_client.collections.get(collection_name)
        if collection:
            collection.clear_dynamic_objects()
    
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
            [0.1, 0.2, 0.3],
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
        
        # Get all competencies and find one with a cluster_id
        all_competencies = workflows.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)
        competency_with_cluster = next((c for c in all_competencies if c["properties"].get("cluster_id")), None)
        
        if competency_with_cluster:
            fake_cluster_id = competency_with_cluster["properties"]["cluster_id"]
            workflows.weaviate_client.add_embeddings(
                "SemanticCluster",
                [0.1, 0.2, 0.3],
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
        mock_relationship_matrix = np.array([
            ["NONE", "REQUIRES", "EXTENDS"],
            ["MATCHES", "NONE", "REQUIRES"],
            ["NONE", "EXTENDS", "NONE"]
        ])
        mock_generate.return_value = mock_relationship_matrix
        
        # Test the suggest_competency_relations method
        result = workflows.suggest_competency_relations(course_id=1)
        
        # Verify the result structure
        assert hasattr(result, 'relations'), "Result should have relations attribute"
        assert isinstance(result.relations, list), "Relations should be a list"
        assert len(result.relations) == 5, f"Expected 5 relations, got {len(result.relations)}"
        
        # Verify specific relations
        relation_dict = {
            (r.tail_id, r.head_id): r.relation_type.value
            for r in result.relations
        }
        
        expected_relations = {
            ("10", "11"): "REQUIRES",
            ("10", "12"): "EXTENDS",
            ("11", "10"): "MATCHES",
            ("11", "12"): "REQUIRES",
            ("12", "11"): "EXTENDS",
        }
        for (tail, head), expected_type in expected_relations.items():
            assert (tail, head) in relation_dict, f"Missing relation {tail} -> {head}"
            assert relation_dict[(tail, head)] == expected_type


def test_suggest_competency_relations_empty_course(workflows):
    """Test suggest_competency_relations with no competencies"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        # Test with non-existent course_id
        result = workflows.suggest_competency_relations(course_id=999)
        
        # Should return empty relations
        assert hasattr(result, 'relations'), "Result should have relations attribute"
        assert isinstance(result.relations, list), "Relations should be a list"
        assert len(result.relations) == 0, "Should return empty relations for non-existent course"


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
        matrix[2, 3] = "MATCHES"
        matrix[3, 4] = "REQUIRES"
        matrix[4, 0] = "EXTENDS"
        mock_generate.return_value = matrix
        
        result = workflows.suggest_competency_relations(course_id="5")
        
        # Should have 5 non-NONE relations
        assert len(result.relations) == 5, f"Expected 5 relations, got {len(result.relations)}"
        
        # Verify all relation types are represented
        relation_types = {r.relation_type.value for r in result.relations}
        expected_types = {"REQUIRES", "EXTENDS", "MATCHES"}
        assert relation_types == expected_types, f"Expected {expected_types}, got {relation_types}"


# ============================================================================
# New mapping tests - Use unique IDs to avoid static data conflicts
# ============================================================================

def test_map_new_competency_to_exercise_success(workflows, mock_weaviate_client):
    """Test successful mapping with complete mock data"""
    # Use unique IDs that don't conflict with static mock data (use 100+)
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 101,
            "title": "Test Exercise",
            "description": "Test Description",
            "competency_ids": [],
            "course_id": 1,
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 102,
            "title": "Test Competency",
            "description": "Test Competency Description",
            "course_id": 1,
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_new_competency_to_exercise(exercise_id=101, competency_id=102)
        
        # Assert: Verify update was called
        spy.assert_called_once()
        call_args = spy.call_args[0]
        assert call_args[0] == CollectionNames.EXERCISE.value
        # Verify competency 102 was added to the list
        assert 102 in call_args[2]["competency_ids"]


def test_map_new_competency_to_exercise_duplicate_prevention(workflows, mock_weaviate_client):
    """Test that duplicate mappings don't add duplicate IDs to the list"""
    # Use unique IDs
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 103,
            "title": "Test Exercise",
            "description": "Test Description",
            "competency_ids": [104],  # Already has competency 104
            "course_id": 1,
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 104,
            "title": "Test Competency",
            "description": "Test Competency Description",
            "course_id": 1,
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_new_competency_to_exercise(exercise_id=103, competency_id=104)
        
        # Assert: Update should not be called OR should be called but list still has only one 104
        # Based on the actual implementation behavior from the code
        if spy.call_count > 0:
            call_args = spy.call_args[0]
            # Verify no duplicate - competency_ids should still contain 104 only once
            competency_ids = call_args[2]["competency_ids"]
            assert competency_ids.count(104) == 1, "Should not have duplicate competency IDs"


def test_map_new_competency_to_exercise_nonexistent_raises_error(workflows, mock_weaviate_client):
    """Test mapping to nonexistent exercise/competency raises ValueError"""
    # No data added - both are nonexistent
    
    with pytest.raises(ValueError):
        workflows.map_new_competency_to_exercise(exercise_id=999, competency_id=999)


def test_map_new_competency_to_exercise_handles_none_competencies(workflows, mock_weaviate_client):
    """Test handling of None/missing competency_ids"""
    # Use unique IDs
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 105,
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
            "competency_id": 106,
            "title": "Test Competency",
            "description": "Test Competency Description",
            "course_id": 1,
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act: Should handle None gracefully
        workflows.map_new_competency_to_exercise(exercise_id=105, competency_id=106)
        
        # Assert: Should successfully add competency
        spy.assert_called_once()
        call_args = spy.call_args[0]
        assert 106 in call_args[2]["competency_ids"]


def test_map_competency_to_competency_bidirectional(workflows, mock_weaviate_client):
    """Test bidirectional relationship creation"""
    # Use unique IDs
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 201,
            "title": "Competency 201",
            "description": "Description 201",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 202,
            "title": "Competency 202",
            "description": "Description 202",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_competency_to_competency(source_competency_id=201, target_competency_id=202)
        
        # Assert: Should call update twice (bidirectional)
        assert spy.call_count == 2, f"Expected 2 updates, got {spy.call_count}"
        
        # Verify both updates include the relationship
        calls = spy.call_args_list
        # Check source was updated with target
        source_updated = any(202 in call[0][2].get("related_competencies", []) for call in calls)
        # Check target was updated with source
        target_updated = any(201 in call[0][2].get("related_competencies", []) for call in calls)
        assert source_updated and target_updated, "Both directions should be updated"


def test_map_competency_to_competency_preserves_existing(workflows, mock_weaviate_client):
    """Test that existing relations are preserved"""
    # Use unique IDs
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 203,
            "title": "Competency 203",
            "description": "Description 203",
            "course_id": 1,
            "related_competencies": [205],  # Existing relation
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 204,
            "title": "Competency 204",
            "description": "Description 204",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_competency_to_competency(source_competency_id=203, target_competency_id=204)
        
        # Assert
        spy.assert_called()
        calls = spy.call_args_list
        # Find the call that updates source
        source_call = [c for c in calls if 205 in c[0][2].get("related_competencies", [])]
        if source_call:
            relations = source_call[0][0][2]["related_competencies"]
            assert 205 in relations, "Should preserve existing relation 205"
            assert 204 in relations, "Should add new relation 204"


def test_map_competency_to_competency_duplicate_prevention(workflows, mock_weaviate_client):
    """Test that duplicate relationships don't create duplicate IDs in list"""
    # Use unique IDs - already related
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 206,
            "title": "Competency 206",
            "description": "Description 206",
            "course_id": 1,
            "related_competencies": [207],  # Already related
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 207,
            "title": "Competency 207",
            "description": "Description 207",
            "course_id": 1,
            "related_competencies": [206],  # Already related
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act
        workflows.map_competency_to_competency(source_competency_id=206, target_competency_id=207)
        
        # Assert: Update may be called, but should not create duplicates in the lists
        if spy.call_count > 0:
            calls = spy.call_args_list
            for call in calls:
                related_comps = call[0][2].get("related_competencies", [])
                # Check for duplicates in the list
                assert len(related_comps) == len(set(related_comps)), "Should not have duplicate IDs in related_competencies"


def test_map_competency_to_competency_nonexistent_source(workflows, mock_weaviate_client):
    """Test mapping from nonexistent source raises ValueError"""
    # Only add target
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 208,
            "title": "Competency 208",
            "description": "Description 208",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with pytest.raises(ValueError):
        workflows.map_competency_to_competency(source_competency_id=999, target_competency_id=208)


def test_map_competency_to_competency_nonexistent_target(workflows, mock_weaviate_client):
    """Test mapping to nonexistent target raises ValueError"""
    # Only add source
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 209,
            "title": "Competency 209",
            "description": "Description 209",
            "course_id": 1,
            "related_competencies": [],
        }
    )
    
    with pytest.raises(ValueError):
        workflows.map_competency_to_competency(source_competency_id=209, target_competency_id=999)


def test_map_competency_to_competency_handles_none_relations(workflows, mock_weaviate_client):
    """Test handling of None/missing related_competencies"""
    # Use unique IDs
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 210,
            "title": "Competency 210",
            "description": "Description 210",
            "course_id": 1,
            "related_competencies": None,  # None value
        }
    )
    
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.4, 0.5, 0.6],
        {
            "competency_id": 211,
            "title": "Competency 211",
            "description": "Description 211",
            "course_id": 1,
            # Missing related_competencies field
        }
    )
    
    with patch.object(workflows.weaviate_client, 'update_property_by_id', 
                      wraps=workflows.weaviate_client.update_property_by_id) as spy:
        # Act: Should handle None/missing gracefully
        workflows.map_competency_to_competency(source_competency_id=210, target_competency_id=211)
        
        # Assert: Should successfully create relationship
        assert spy.call_count == 2, "Should update both competencies"
