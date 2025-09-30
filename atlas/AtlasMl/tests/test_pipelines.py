import pytest
import uuid
from atlasml.clients.weaviate import CollectionNames
from atlasml.ml.pipeline_workflows import PipelineWorkflows
from atlasml.models.competency import ExerciseWithCompetencies, Competency
from unittest.mock import patch
import numpy as np


# ============================================================================
# FakeWeaviateClient - Stateful mock for pipeline integration tests
# ============================================================================

class FakeWeaviateClient:
    """Lightweight stateful mock for pipeline tests"""
    def __init__(self):
        self.collections = {
            "Exercise": [],
            "Competency": [],
            "SemanticCluster": [],
        }

    def _ensure_collections_exist(self):
        pass

    def add_embeddings(self, collection, vector, properties):
        obj_id = (
            properties.get("text_id")
            or properties.get("competency_id")
            or properties.get("exercise_id")
            or properties.get("cluster_id")
            or str(uuid.uuid4())
        )
        obj = {
            "id": obj_id,
            "vector": {"default": vector},
            "properties": properties.copy(),
        }
        self.collections[collection].append(obj)
        return obj_id

    def get_all_embeddings(self, collection):
        return self.collections[collection][:]

    def update_property_by_id(self, collection, obj_id, new_properties):
        for obj in self.collections[collection]:
            # Handle both string and int IDs
            if str(obj["id"]) == str(obj_id) or obj["id"] == obj_id:
                obj["properties"].update(new_properties)
                return
        raise KeyError(f"id: {obj_id} not found in {collection}")

    def get_embeddings_by_property(self, collection, property_key, value):
        results = []
        for obj in self.collections[collection]:
            obj_value = obj["properties"].get(property_key)
            # Handle type coercion for comparison
            if obj_value == value or str(obj_value) == str(value):
                results.append(obj)
        return results

    def delete_all_data_from_collection(self, collection_name):
        if collection_name in self.collections:
            self.collections[collection_name] = []


@pytest.fixture
def workflows():
    """Create PipelineWorkflows with FakeWeaviateClient"""
    wf = PipelineWorkflows(weaviate_client=FakeWeaviateClient())
    # Clear all collections before each test
    for collection in wf.weaviate_client.collections:
        wf.weaviate_client.delete_all_data_from_collection(collection)
    return wf


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
        
        all_comps = workflows.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)
        if len(all_comps) > 3:
            fake_cluster_id = all_comps[3]["properties"]["cluster_id"]
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
        workflows.initial_competencies(competencies)
        
        mock_relationship_matrix = np.array([
            ["NONE", "REQUIRES", "EXTENDS"],
            ["MATCHES", "NONE", "REQUIRES"],
            ["NONE", "EXTENDS", "NONE"]
        ])
        mock_generate.return_value = mock_relationship_matrix
        
        result = workflows.suggest_competency_relations(course_id=1)
        
        assert hasattr(result, 'relations')
        assert isinstance(result.relations, list)
        assert len(result.relations) == 5


def test_suggest_competency_relations_empty_course(workflows):
    """Test suggest_competency_relations with no competencies"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        result = workflows.suggest_competency_relations(course_id=999)
        assert len(result.relations) == 0


def test_suggest_competency_relations_single_competency(workflows):
    """Test suggest_competency_relations with only one competency"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
        single_competency = [
            Competency(
                id=20,
                title="Single Competency",
                description="The only competency in this course",
                course_id=2,
            )
        ]
        workflows.initial_competencies(single_competency)
        mock_generate.return_value = np.array([["NONE"]])
        result = workflows.suggest_competency_relations(course_id=2)
        assert len(result.relations) == 0


def test_suggest_competency_relations_two_competencies(workflows):
    """Test suggest_competency_relations with exactly two competencies"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
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
        mock_generate.return_value = np.array([
            ["NONE", "REQUIRES"],
            ["EXTENDS", "NONE"]
        ])
        result = workflows.suggest_competency_relations(course_id="3")
        assert len(result.relations) == 2


def test_suggest_competency_relations_all_none_matrix(workflows):
    """Test suggest_competency_relations when all relations are NONE"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
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
        mock_generate.return_value = np.array([
            ["NONE", "NONE"],
            ["NONE", "NONE"]
        ])
        result = workflows.suggest_competency_relations(course_id="4")
        assert len(result.relations) == 0


def test_suggest_competency_relations_large_course(workflows):
    """Test suggest_competency_relations with many competencies"""
    with patch("atlasml.ml.pipeline_workflows.generate_competency_relationship") as mock_generate:
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
        
        matrix = np.full((5, 5), "NONE", dtype=object)
        matrix[0, 1] = "REQUIRES"
        matrix[1, 2] = "EXTENDS"
        matrix[2, 3] = "MATCHES"
        matrix[3, 4] = "REQUIRES"
        matrix[4, 0] = "EXTENDS"
        mock_generate.return_value = matrix
        
        result = workflows.suggest_competency_relations(course_id="5")
        assert len(result.relations) == 5


# ============================================================================
# New mapping tests
# ============================================================================

def test_map_new_competency_to_exercise_success(workflows):
    """Test successful mapping"""
    # Add exercise
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
    
    # Add competency
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
    
    # Act
    workflows.map_new_competency_to_exercise(exercise_id=101, competency_id=102)
    
    # Assert
    exercise_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.EXERCISE.value, "exercise_id", 101
    )
    assert len(exercise_data) == 1
    assert 102 in exercise_data[0]["properties"]["competency_ids"]


def test_map_new_competency_to_exercise_duplicate_prevention(workflows):
    """Test that duplicate mappings don't create duplicate IDs"""
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 103,
            "title": "Test Exercise",
            "description": "Test Description",
            "competency_ids": [104],
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
    
    workflows.map_new_competency_to_exercise(exercise_id=103, competency_id=104)
    
    exercise_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.EXERCISE.value, "exercise_id", 103
    )
    # Should not have duplicates
    assert exercise_data[0]["properties"]["competency_ids"].count(104) == 1


def test_map_new_competency_to_exercise_nonexistent_raises_error(workflows):
    """Test mapping to nonexistent exercise/competency raises ValueError"""
    with pytest.raises(ValueError):
        workflows.map_new_competency_to_exercise(exercise_id=999, competency_id=999)


def test_map_new_competency_to_exercise_handles_none_competencies(workflows):
    """Test handling of None/missing competency_ids"""
    workflows.weaviate_client.add_embeddings(
        CollectionNames.EXERCISE.value,
        [0.1, 0.2, 0.3],
        {
            "exercise_id": 105,
            "title": "Test Exercise",
            "description": "Test Description",
            "competency_ids": None,
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
    
    workflows.map_new_competency_to_exercise(exercise_id=105, competency_id=106)
    
    exercise_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.EXERCISE.value, "exercise_id", 105
    )
    assert 106 in exercise_data[0]["properties"]["competency_ids"]


def test_map_competency_to_competency_bidirectional(workflows):
    """Test bidirectional relationship creation"""
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
    
    workflows.map_competency_to_competency(source_competency_id=201, target_competency_id=202)
    
    source_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 201
    )
    target_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 202
    )
    
    assert 202 in source_data[0]["properties"]["related_competencies"]
    assert 201 in target_data[0]["properties"]["related_competencies"]


def test_map_competency_to_competency_preserves_existing(workflows):
    """Test that existing relations are preserved"""
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 203,
            "title": "Competency 203",
            "description": "Description 203",
            "course_id": 1,
            "related_competencies": [205],
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
    
    workflows.map_competency_to_competency(source_competency_id=203, target_competency_id=204)
    
    source_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 203
    )
    
    relations = source_data[0]["properties"]["related_competencies"]
    assert 205 in relations
    assert 204 in relations


def test_map_competency_to_competency_duplicate_prevention(workflows):
    """Test that duplicate relationships don't create duplicate IDs"""
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 206,
            "title": "Competency 206",
            "description": "Description 206",
            "course_id": 1,
            "related_competencies": [207],
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
            "related_competencies": [206],
        }
    )
    
    workflows.map_competency_to_competency(source_competency_id=206, target_competency_id=207)
    
    source_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 206
    )
    target_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 207
    )
    
    # Should not have duplicates
    assert source_data[0]["properties"]["related_competencies"].count(207) == 1
    assert target_data[0]["properties"]["related_competencies"].count(206) == 1


def test_map_competency_to_competency_nonexistent_source(workflows):
    """Test mapping from nonexistent source raises ValueError"""
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


def test_map_competency_to_competency_nonexistent_target(workflows):
    """Test mapping to nonexistent target raises ValueError"""
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


def test_map_competency_to_competency_handles_none_relations(workflows):
    """Test handling of None/missing related_competencies"""
    workflows.weaviate_client.add_embeddings(
        CollectionNames.COMPETENCY.value,
        [0.1, 0.2, 0.3],
        {
            "competency_id": 210,
            "title": "Competency 210",
            "description": "Description 210",
            "course_id": 1,
            "related_competencies": None,
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
        }
    )
    
    workflows.map_competency_to_competency(source_competency_id=210, target_competency_id=211)
    
    source_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 210
    )
    target_data = workflows.weaviate_client.get_embeddings_by_property(
        CollectionNames.COMPETENCY.value, "competency_id", 211
    )
    
    assert 211 in source_data[0]["properties"]["related_competencies"]
    assert 210 in target_data[0]["properties"]["related_competencies"]
