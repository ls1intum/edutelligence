import numpy as np
from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity
from atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension


class ClusterToCompetencyPipeline:
    """
    ClusterToCompetencyPipeline orchestrates the workflow of assigning new competency texts
    to their closest existing cluster medoids and persisting those relationships in Weaviate.

    Attributes:
        weaviate_client: A Weaviate client instance used to fetch and store embedding data.
        clusters: A list of cluster entries, each containing a medoid embedding fetched from Weaviate.
        competencies: A list of competency entries fetched from Weaviate to be processed.

    Methods:
        run() -> None:
            1. Fetches all cluster medoid embeddings and all competency records from Weaviate.
            2. For each competency, generates a local embedding.
            3. Computes cosine similarity between the competency embedding and each cluster medoid.
            4. Identifies the most similar medoid (highest cosine similarity).
            5. Associates the competency with that cluster by writing the embedding and linkage
               back into the competency collection in Weaviate.
    """

    def __init__(self):
        self.clusters = None
        self.competencies = None
        self.weaviate_client = get_weaviate_client()

    def run(self):
        self.clusters = self.weaviate_client.get_all_embeddings(CollectionNames.CLUSTER.value)
        medoids = np.array(entry["vector"] for entry in self.clusters)
        self.competencies = self.weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)

        for competency in self.competencies:
            uuid, embedding = generate_embeddings_local(competency["properties"]["id"], competency["properties"]["text"])
            similarity_score = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
            best_medoid_idx = int(np.argmax(similarity_score))
            properties = { "properties": [{
                "id": uuid ,
                "name" : competency["properties"]["name"],
                "text": competency["properties"]["text"],
                "unit_id": competency["properties"]["unit_id"],
                "category" : competency["properties"]["category"],
                "competencyID": self.clusters[best_medoid_idx]["properties"]["id"]
            }]}
            self.weaviate_client.add_embeddings(CollectionNames.COMPETENCY.value, embedding, properties)
