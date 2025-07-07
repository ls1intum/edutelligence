import pytest
import uuid
from sympy import false
from weaviate.collections.classes.filters import Filter
from atlasml.clients.weaviate import CollectionNames
from atlasml.ml.MLPipelines.PipelineWorkflows import PipelineWorkflows

@pytest.fixture(scope="function")
def workflows():
    wf = PipelineWorkflows()
    collections = [CollectionNames.TEXT.value, CollectionNames.COMPETENCY.value, CollectionNames.CLUSTERCENTER.value]
    for name in collections:
        try:
            wf.weaviate_client.delete_all_data_from_collection(name)
        except Exception:
            pass
    wf.weaviate_client._ensure_collections_exist()
    return wf

def test_initial_texts_integration(workflows):
    texts = [f"Integration text {uuid.uuid4()}" for _ in range(2)]
    workflows.initial_texts(texts)
    inserted = workflows.weaviate_client.get_all_embeddings("Text")
    found_texts = [item["properties"]["text"] for item in inserted]
    for t in texts:
        assert any(t == ft for ft in found_texts)

def test_initial_competencies_integration(workflows):
    competencies = [
        {"title": f"Integration Competency {uuid.uuid4()}", "description": f"Description {i}"}
        for i in range(2)
    ]
    workflows.initial_competencies(competencies)
    inserted = workflows.weaviate_client.get_all_embeddings("Competency")
    found_titles = [item["properties"]["name"] for item in inserted]
    for comp in competencies:
        assert any(comp["title"] == ft for ft in found_titles)

def test_initial_cluster_pipeline_integration(workflows):
    texts = [
        "Lists",
        "Arrays",
        "Variables",
        "Dictionaries",
        "Functions",
        "Loops",
        "Tuples",
        "Sets",
        "Classes",
        "Recursion"
    ]
    workflows.initial_texts(texts)
    workflows.initial_competencies([
        {"title": f"Data Structures Mastery",
         "description": "Ability to understand and efficiently use core data structures such as lists, arrays, dictionaries, tuples, and sets. This includes selecting the appropriate structure for a task and applying common operations like searching, sorting, and modifying data."},
        {"title": f"Programming Fundamentals",
         "description": "Proficiency in core programming concepts, including variables, loops, and functions. Capable of writing, reading, and debugging code that uses these basic elements to implement algorithms and solve problems."},
        {"title": f"Object-Oriented and Algorithmic Thinking",
         "description": "Understanding of object-oriented programming concepts such as classes and recursion, and their role in organizing code and solving complex problems. Can design class hierarchies, use recursion effectively, and apply these patterns to real-world scenarios."}
    ])
    workflows.initial_cluster_pipeline()
    clusters = workflows.weaviate_client.get_all_embeddings("ClusterCenter")
    assert clusters, "Clusters were not created!"

def test_initial_cluster_to_competencyPipeline_integration(workflows):
    texts = [
        "Lists",
        "Arrays",
        "Variables",
        "Dictionaries",
        "Functions",
        "Loops",
        "Tuples",
        "Sets",
        "Classes",
        "Recursion"
    ]
    workflows.initial_texts(texts)
    workflows.initial_competencies([
        {"title": f"Data Structures Mastery",
         "description": "Ability to understand and efficiently use core data structures such as lists, arrays, dictionaries, tuples, and sets. This includes selecting the appropriate structure for a task and applying common operations like searching, sorting, and modifying data."},
        {"title": f"Programming Fundamentals",
         "description": "Proficiency in core programming concepts, including variables, loops, and functions. Capable of writing, reading, and debugging code that uses these basic elements to implement algorithms and solve problems."},
        {"title": f"Object-Oriented and Algorithmic Thinking",
         "description": "Understanding of object-oriented programming concepts such as classes and recursion, and their role in organizing code and solving complex problems. Can design class hierarchies, use recursion effectively, and apply these patterns to real-world scenarios."}
    ])
    workflows.initial_cluster_pipeline()
    workflows.initial_cluster_to_competencyPipeline()
    clusters = workflows.weaviate_client.get_all_embeddings("ClusterCenter")
    competencies = workflows.weaviate_client.get_all_embeddings("Competency")
    assert clusters, "Clusters were not created!"
    assert competencies, "Competencies missing!"

def test_newTextPipeline_integration(workflows):
    workflows.initial_competencies([
        {"title": f"Data Structures Mastery",
         "description": "Ability to understand and efficiently use core data structures such as lists, arrays, dictionaries, tuples, and sets. This includes selecting the appropriate structure for a task and applying common operations like searching, sorting, and modifying data."},
        {"title": f"Programming Fundamentals",
         "description": "Proficiency in core programming concepts, including variables, loops, and functions. Capable of writing, reading, and debugging code that uses these basic elements to implement algorithms and solve problems."},
        {"title": f"Object-Oriented and Algorithmic Thinking",
         "description": "Understanding of object-oriented programming concepts such as classes and recursion, and their role in organizing code and solving complex problems. Can design class hierarchies, use recursion effectively, and apply these patterns to real-world scenarios."}
    ])
    texts = [
        "Lists",
        "Arrays",
        "Variables",
        "Dictionaries",
        "Functions",
        "Loops",
        "Tuples",
        "Sets",
        "Classes",
        "Recursion"
    ]
    workflows.initial_texts(texts)
    workflows.initial_cluster_pipeline()
    test_id = str(uuid.uuid4())
    test_text = "object-oriented programming"
    competency_id = workflows.newTextPipeline(test_text, test_id)
    texts = workflows.weaviate_client.get_all_embeddings("Text")
    found = any(t["properties"].get("text_id") == test_id for t in texts)
    assert found