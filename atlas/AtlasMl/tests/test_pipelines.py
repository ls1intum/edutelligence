import pytest
import uuid

from atlasml.clients.weaviate import CollectionNames
from atlasml.ml.pipeline_workflows import PipelineWorkflows
from atlasml.models.competency import ExerciseWithCompetencies, Competency
from unittest.mock import patch
import numpy as np


@pytest.fixture
def workflows(mock_weaviate_client):
    """Create PipelineWorkflows with mock weaviate client from conftest """
    return PipelineWorkflows(weaviate_client=mock_weaviate_client)


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


def test_map_new_competency_to_exercise_integration(workflows):
    """Test the map_new_competency_to_exercise pipeline method"""
    # Setup test data - create exercise and competency
    exercise = ExerciseWithCompetencies(
        id=1,
        title="Test Exercise",
        description="Test exercise for mapping",
        competencies=[],  # Empty initially
        course_id=1,
    )

    competency = Competency(
        id=1,
        title="Test Competency",
        description="Test competency for mapping",
        course_id=1,
    )

    # Add test data to workflows
    workflows.save_exercise_to_weaviate(exercise)
    workflows.save_competency_to_weaviate(competency)

    # Test the mapping
    workflows.map_new_competency_to_exercise(exercise_id=1, competency_id=1)

    # Verify the mapping was successful
    updated_exercise_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.EXERCISE.value, "exercise_id", 1
    )

    assert len(updated_exercise_data) == 1, "Exercise should exist"
    updated_competency_ids = updated_exercise_data[0]["properties"]["competency_ids"]
    assert 1 in updated_competency_ids, "Competency should be mapped to exercise"


def test_map_new_competency_to_exercise_already_mapped(workflows):
    """Test mapping a competency that's already mapped to exercise"""
    # Setup test data - exercise with existing competency
    exercise = ExerciseWithCompetencies(
        id=2,
        title="Test Exercise 2",
        description="Test exercise with existing competency",
        competencies=[1],  # Already has competency 1
        course_id=1,
    )

    competency = Competency(
        id=1,
        title="Test Competency",
        description="Test competency already mapped",
        course_id=1,
    )

    # Add test data to workflows
    workflows.save_exercise_to_weaviate(exercise)
    workflows.save_competency_to_weaviate(competency)

    # Test mapping the same competency again
    workflows.map_new_competency_to_exercise(exercise_id=2, competency_id=1)

    # Verify no duplicate mapping
    updated_exercise_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.EXERCISE.value, "exercise_id", 2
    )

    updated_competency_ids = updated_exercise_data[0]["properties"]["competency_ids"]
    assert updated_competency_ids.count(1) == 1, "Competency should not be duplicated"


def test_map_new_competency_to_exercise_nonexistent_exercise(workflows):
    """Test mapping to nonexistent exercise raises ValueError"""
    competency = Competency(
        id=1,
        title="Test Competency",
        description="Test competency",
        course_id=1,
    )

    workflows.save_competency_to_weaviate(competency)

    # Test mapping to nonexistent exercise
    with pytest.raises(ValueError, match="No exercise or competency found for mapping"):
        workflows.map_new_competency_to_exercise(exercise_id=999, competency_id=1)


def test_map_new_competency_to_exercise_nonexistent_competency(workflows):
    """Test mapping nonexistent competency raises ValueError"""
    exercise = ExerciseWithCompetencies(
        id=1,
        title="Test Exercise",
        description="Test exercise",
        competencies=[],
        course_id=1,
    )

    workflows.save_exercise_to_weaviate(exercise)

    # Test mapping nonexistent competency
    with pytest.raises(ValueError, match="No exercise or competency found for mapping"):
        workflows.map_new_competency_to_exercise(exercise_id=1, competency_id=999)


def test_map_competency_to_competency_integration(workflows):
    """Test the map_competency_to_competency pipeline method"""
    # Setup test competencies
    competency1 = Competency(
        id=1,
        title="Python Basics",
        description="Basic Python programming",
        course_id=1,
    )

    competency2 = Competency(
        id=2,
        title="Data Structures",
        description="Understanding data structures",
        course_id=1,
    )

    # Add competencies to workflows
    workflows.save_competency_to_weaviate(competency1)
    workflows.save_competency_to_weaviate(competency2)

    # Test the bidirectional mapping
    workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)

    # Verify bidirectional relationship was created
    comp1_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 1
    )
    comp2_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 2
    )

    assert len(comp1_data) == 1, "Source competency should exist"
    assert len(comp2_data) == 1, "Target competency should exist"

    comp1_related = comp1_data[0]["properties"].get("related_competencies", [])
    comp2_related = comp2_data[0]["properties"].get("related_competencies", [])

    assert 2 in comp1_related, "Competency 1 should be related to competency 2"
    assert 1 in comp2_related, "Competency 2 should be related to competency 1"


def test_map_competency_to_competency_existing_relations(workflows):
    """Test mapping competencies that already have existing relations"""
    # Setup competencies with existing relations
    competency1 = Competency(
        id=1,
        title="Python Basics",
        description="Basic Python programming",
        course_id=1,
    )

    competency2 = Competency(
        id=2,
        title="Data Structures",
        description="Understanding data structures",
        course_id=1,
    )

    competency3 = Competency(
        id=3,
        title="Algorithms",
        description="Algorithm design and analysis",
        course_id=1,
    )

    # Add competencies to workflows
    workflows.save_competency_to_weaviate(competency1)
    workflows.save_competency_to_weaviate(competency2)
    workflows.save_competency_to_weaviate(competency3)

    # Create initial relationship: comp1 <-> comp3
    workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=3)

    # Add new relationship: comp1 <-> comp2
    workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)

    # Verify comp1 has both relations
    comp1_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 1
    )
    comp1_related = comp1_data[0]["properties"].get("related_competencies", [])

    assert 2 in comp1_related, "Competency 1 should be related to competency 2"
    assert 3 in comp1_related, "Competency 1 should still be related to competency 3"
    assert len(comp1_related) == 2, "Competency 1 should have exactly 2 relations"


def test_map_competency_to_competency_self_mapping(workflows):
    """Test mapping a competency to itself"""
    competency = Competency(
        id=1,
        title="Self-referential Competency",
        description="A competency that references itself",
        course_id=1,
    )

    workflows.save_competency_to_weaviate(competency)

    # Test self-mapping
    workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=1)

    # Verify self-relation was created
    comp_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 1
    )
    comp_related = comp_data[0]["properties"].get("related_competencies", [])

    assert 1 in comp_related, "Competency should be related to itself"
    assert len(comp_related) == 1, "Should have exactly one self-relation"


def test_map_competency_to_competency_nonexistent_source(workflows):
    """Test mapping from nonexistent source competency raises ValueError"""
    competency = Competency(
        id=2,
        title="Target Competency",
        description="Target competency that exists",
        course_id=1,
    )

    workflows.save_competency_to_weaviate(competency)

    # Test mapping from nonexistent source
    with pytest.raises(ValueError, match="Source or target competency not found for mapping"):
        workflows.map_competency_to_competency(source_competency_id=999, target_competency_id=2)


def test_map_competency_to_competency_nonexistent_target(workflows):
    """Test mapping to nonexistent target competency raises ValueError"""
    competency = Competency(
        id=1,
        title="Source Competency",
        description="Source competency that exists",
        course_id=1,
    )

    workflows.save_competency_to_weaviate(competency)

    # Test mapping to nonexistent target
    with pytest.raises(ValueError, match="Source or target competency not found for mapping"):
        workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=999)


def test_map_competency_to_competency_duplicate_mapping(workflows):
    """Test mapping competencies that are already mapped doesn't create duplicates"""
    # Setup test competencies
    competency1 = Competency(
        id=1,
        title="Python Basics",
        description="Basic Python programming",
        course_id=1,
    )

    competency2 = Competency(
        id=2,
        title="Data Structures",
        description="Understanding data structures",
        course_id=1,
    )

    # Add competencies to workflows
    workflows.save_competency_to_weaviate(competency1)
    workflows.save_competency_to_weaviate(competency2)

    # Create the relationship twice
    workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)
    workflows.map_competency_to_competency(source_competency_id=1, target_competency_id=2)

    # Verify no duplicates
    comp1_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 1
    )
    comp2_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 2
    )

    comp1_related = comp1_data[0]["properties"].get("related_competencies", [])
    comp2_related = comp2_data[0]["properties"].get("related_competencies", [])

    assert comp1_related.count(2) == 1, "Should not have duplicate relations"
    assert comp2_related.count(1) == 1, "Should not have duplicate relations"


