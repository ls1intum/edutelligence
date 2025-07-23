import pytest
import uuid
from atlasml.ml.MLPipelines.PipelineWorkflows import PipelineWorkflows
from atlasml.models.competency import ExerciseWithCompetencies, Competency, CompetencyTaxonomy


@pytest.fixture
def workflows():
    wf = PipelineWorkflows(weaviate_client=FakeWeaviateClient())
    # Clear all collections before each test
    for collection in wf.weaviate_client.collections:
        wf.weaviate_client.delete_all_data_from_collection(collection)
    return wf

def test_initial_texts_integration(workflows):
    texts = [ExerciseWithCompetencies(id=str(uuid.uuid4()),
                                      title="Integration Exercise",
                                      description="Integration Exercise Description",
                                      competencies=[])  for _ in range(2)]
    workflows.initial_exercises(texts)
    inserted = workflows.weaviate_client.get_all_embeddings("Exercise")
    found_texts = [item["properties"]["description"] for item in inserted]
    for t in texts:
        assert any(t.description == ft for ft in found_texts)

def test_initial_competencies_integration(workflows):
    competencies = [
        Competency(id=str(uuid.uuid4()), title="Integration Competency", description="Description", taxonomy=CompetencyTaxonomy.ANALYZE)
        for i in range(2)
    ]

    workflows.initial_competencies(competencies)
    inserted = workflows.weaviate_client.get_all_embeddings("Competency")
    found_titles = [item["properties"]["title"] for item in inserted]
    for comp in competencies:
        assert any(comp.title == ft for ft in found_titles)

def test_initial_cluster_pipeline_integration(workflows):
    titles = ["Lists", "Arrays", "Variables", "Dictionaries", "Functions", "Loops", "Tuples", "Sets", "Classes", "Recursion"]
    texts = [ExerciseWithCompetencies(id=str(uuid.uuid4()),
                                      title=title,
                                      description=title,
                                      competencies=[])  for title in titles]
    workflows.initial_exercises(texts)

    competencies = [
        Competency(id=str(uuid.uuid4()), title="Data Structures Mastery", description="Ability to understand and efficiently use core data structures such as lists, arrays, dictionaries, tuples, and sets. This includes selecting the appropriate structure for a task and applying common operations like searching, sorting, and modifying data.", taxonomy=CompetencyTaxonomy.ANALYZE),
        Competency(id=str(uuid.uuid4()), title="Programming Fundamentals", description="Proficiency in core programming concepts, including variables, loops, and functions. Capable of writing, reading, and debugging code that uses these basic elements to implement algorithms and solve problems.", taxonomy=CompetencyTaxonomy.ANALYZE),
        Competency(id=str(uuid.uuid4()), title="Object-Oriented and Algorithmic Thinking", description="Understanding of object-oriented programming concepts such as classes and recursion, and their role in organizing code and solving complex problems. Can design class hierarchies, use recursion effectively, and apply these patterns to real-world scenarios.", taxonomy=CompetencyTaxonomy.ANALYZE)
    ]

    workflows.initial_competencies(competencies)
    workflows.initial_cluster_pipeline()
    clusters = workflows.weaviate_client.get_all_embeddings("ClusterCenter")
    assert clusters, "Clusters were not created!"

def test_initial_cluster_to_competencyPipeline_integration(workflows):
    titles = ["Lists", "Arrays", "Variables", "Dictionaries", "Functions", "Loops", "Tuples", "Sets", "Classes", "Recursion"]
    texts = [ExerciseWithCompetencies(id=str(uuid.uuid4()),
                                      title=title,
                                      description=title,
                                      competencies=[])  for title in titles]
    workflows.initial_exercises(texts)

    competencies = [
        Competency(id=str(uuid.uuid4()), title="Data Structures Mastery", description="Ability to understand and efficiently use core data structures such as lists, arrays, dictionaries, tuples, and sets. This includes selecting the appropriate structure for a task and applying common operations like searching, sorting, and modifying data.", taxonomy=CompetencyTaxonomy.ANALYZE),
        Competency(id=str(uuid.uuid4()), title="Programming Fundamentals", description="Proficiency in core programming concepts, including variables, loops, and functions. Capable of writing, reading, and debugging code that uses these basic elements to implement algorithms and solve problems.", taxonomy=CompetencyTaxonomy.ANALYZE),
        Competency(id=str(uuid.uuid4()), title="Object-Oriented and Algorithmic Thinking", description="Understanding of object-oriented programming concepts such as classes and recursion, and their role in organizing code and solving complex problems. Can design class hierarchies, use recursion effectively, and apply these patterns to real-world scenarios.", taxonomy=CompetencyTaxonomy.ANALYZE)
    ]

    workflows.initial_competencies(competencies)
    workflows.initial_cluster_pipeline()
    workflows.initial_cluster_to_competency_pipeline()
    clusters = workflows.weaviate_client.get_all_embeddings("ClusterCenter")
    competencies = workflows.weaviate_client.get_all_embeddings("Competency")
    assert clusters, "Clusters were not created!"
    assert competencies, "Competencies missing!"

def test_newTextPipeline_integration(workflows):
    competencies = [
        Competency(id=str(uuid.uuid4()), title="Data Structures Mastery", description="Ability to understand and efficiently use core data structures such as lists, arrays, dictionaries, tuples, and sets. This includes selecting the appropriate structure for a task and applying common operations like searching, sorting, and modifying data.", taxonomy=CompetencyTaxonomy.ANALYZE),
        Competency(id=str(uuid.uuid4()), title="Programming Fundamentals", description="Proficiency in core programming concepts, including variables, loops, and functions. Capable of writing, reading, and debugging code that uses these basic elements to implement algorithms and solve problems.", taxonomy=CompetencyTaxonomy.ANALYZE),
        Competency(id=str(uuid.uuid4()), title="Object-Oriented and Algorithmic Thinking", description="Understanding of object-oriented programming concepts such as classes and recursion, and their role in organizing code and solving complex problems. Can design class hierarchies, use recursion effectively, and apply these patterns to real-world scenarios.", taxonomy=CompetencyTaxonomy.ANALYZE)
    ]
    workflows.initial_competencies(competencies)
    titles = ["Lists", "Arrays", "Variables", "Dictionaries", "Functions", "Loops", "Tuples", "Sets", "Classes", "Recursion"]
    texts = [ExerciseWithCompetencies(id=str(uuid.uuid4()),
                                      title=title,
                                      description=title,
                                      competencies=[])  for title in titles]
    workflows.initial_exercises(texts)
    workflows.initial_cluster_pipeline()
    test_text = "object-oriented programming"
    competency = workflows.newTextPipeline(test_text)
    assert competency, "Competency ID not found!"


class FakeWeaviateClient:
    def __init__(self):
        self.collections = {
            "Exercise": [],
            "Competency": [],
            "ClusterCenter": [],
        }

    def _ensure_collections_exist(self):
        # Dummy method to match real client interface
        pass

    def add_embeddings(self, collection, vector, properties):
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