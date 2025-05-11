import numpy as np
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity
from atlasml.ml.VectorEmbeddings.ModelDimension import ModelDimension

class NewTextPipeline:
    """
    NewTextPipeline orchestrates text processing by generating embeddings for a single text input
    and computing its similarity with existing cluster medoids.
    
    Args:
        text (str): Input text to be embedded and processed..
        uuid (str): Unique identifier for the input text.
    
    Attributes:
        best_medoid_idx (int): Index of the most similar medoid found.
        similarity_scores (numpy.ndarray): Array of similarity scores between input text and medoids.
        text (str): The input text to be embedded and processed.
        uuid (str): The unique identifier for the text.
    """
    def __init__(self, text: str, uuid: str):
        self.best_medoid_idx = None
        self.similarity_scores = None
        self.text = text
        self.uuid = uuid

    def run(self):
        # TODO: Get all text data from Artemis
        text = self.text
        uuid = self.uuid

        # TODO: Save embedding to VectorDB
        embedding_id, embedding = generate_embeddings_local(uuid, text)

        # TODO: Get medoids from DB
        medoids = np.array([])
        similarity_scores = np.array(compute_cosine_similarity(embedding, medoid) for medoid in medoids)
        best_medoid_idx = int(np.argmax(similarity_scores))

        # TODO: Save label and the embedding to DB
        self.similarity_scores = similarity_scores
        self.best_medoid_idx = best_medoid_idx

        return self.similarity_scores, self.best_medoid_idx

