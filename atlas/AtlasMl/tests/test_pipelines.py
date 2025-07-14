import pytest
import uuid
from atlasml.ml.MLPipelines.PipelineWorkflows import PipelineWorkflows

@pytest.fixture
def workflows():
    wf = PipelineWorkflows(weaviate_client=FakeWeaviateClient())
    # Clear all collections before each test
    for collection in wf.weaviate_client.collections:
        wf.weaviate_client.delete_all_data_from_collection(collection)
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

def test_feedbackLoopPipeline_integration(workflows):
    # Setup: Create one text, one competency, and one cluster
    text_id = str(uuid.uuid4())
    text_id2 = str(uuid.uuid4())
    competency_id = str(uuid.uuid4())
    cluster_id = str(uuid.uuid4())

    # Insert text with no competency_ids
    workflows.weaviate_client.collections["Text"].append({
        "id": text_id,
        "vector": {"default": [0.5, 0.5]},
        "properties": {
            "text_id": text_id,
            "text": "Feedback test text",
            "competency_ids": []
        }
    })
    workflows.weaviate_client.collections["Text"].append({
        "id": text_id2,
        "vector": {"default": [0.1, 0.9]},
        "properties": {
            "text_id": text_id,
            "text": "Feedback test text",
            "competency_ids": [competency_id]
        }
    })

    # Insert competency referencing the cluster
    workflows.weaviate_client.collections["Competency"].append({
        "id": competency_id,
        "vector": {"default": [0.2, 0.8]},
        "properties": {
            "competency_id": competency_id,
            "name": "Feedback Competency",
            "text": "Feedback description",
            "cluster_id": cluster_id
        }
    })

    # Insert cluster
    workflows.weaviate_client.collections["ClusterCenter"].append({
        "id": cluster_id,
        "vector": {"default": [0.1, 0.9]},
        "properties": {
            "cluster_id": cluster_id
        }
    })

    # Call the feedbackLoopPipeline
    workflows.feedbackLoopPipeline(text_id, competency_id)

    # Assert that the text now contains the competency_id in its competency_ids
    updated_text = workflows.weaviate_client.get_embeddings_by_property("Text", "text_id", text_id)[0]
    assert competency_id in updated_text["properties"]["competency_ids"]

    # Optionally, check that the cluster has a new centroid (implementation dependent)
    clusters = workflows.weaviate_client.get_all_embeddings("ClusterCenter")
    found = any(cluster["id"] == cluster_id for cluster in clusters)
    assert found, "Cluster should still exist"


class FakeWeaviateClient:
    def __init__(self):
        self.collections = {
            "Text": [],
            "Competency": [],
            "ClusterCenter": [],
        }

    def add_embeddings(self, collection, vector, properties):
        # Always generate or use a unique object UUID as the top-level "id"
        obj_id = (
            properties.get("text_id") or
            properties.get("competency_id") or
            properties.get("cluster_id") or
            str(uuid.uuid4())
        )
        obj = {
            "id": obj_id,
            "vector": vector if isinstance(vector, dict) else {"default": vector},
            "properties": properties.copy()
        }
        self.collections[collection].append(obj)
        return obj_id

    def get_all_embeddings(self, collection):
        # Return a list of all objects (each is a dict with "id", "vector", "properties")
        return self.collections[collection][:]

    def update_property_by_id(self, collection, obj_id, new_properties):
        for obj in self.collections[collection]:
            if obj["id"] == obj_id:
                obj["properties"].update(new_properties)
                return
        raise KeyError(f'id: {obj_id} not found in {collection}')

    def get_embeddings_by_property(self, collection, property_key, value):
        return [
            obj for obj in self.collections[collection]
            if obj["properties"].get(property_key) == value
        ]

    def delete_all_data_from_collection(self, collection):
        self.collections[collection] = []