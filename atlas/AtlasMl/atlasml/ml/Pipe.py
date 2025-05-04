import pandas as pd
import numpy as np
from atlasml.ml.VectorEmbeddings.FallbackModel import generate_embeddings_local
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan, SimilarityMetric
from atlasml.ml.SimilarityMeasurement.Cosine import compute_cosine_similarity
from sklearn.metrics.pairwise import cosine_similarity

# Get Text
text = "This is an apple."
uuid = "UUID"
# TODO: @Arda Prepare the text

# Get vector embeddings
# embedding_id, embedding = generate_embeddings_openai(uuid, text) TODO: Get API key for OpenAI
embedding_id, embedding = generate_embeddings_local(uuid, text)
# TODO: @Ufuk Save embeddings in VectorDB

# TODO: @Ufuk Load the embeddings from VectorDB
# Currently Local embedding
df = pd.read_csv("embeddings.csv", index_col=0)
embeddings = df.values

# Cluster texts and get cluster centroids
labels, centroids, medoids = apply_hdbscan(embeddings, eps=0.1, min_samples=5, metric=SimilarityMetric.cosine.value, min_cluster_size=5)

# Compute pairwise cosine similarities between medoids
similarity_matrix = cosine_similarity(medoids)
print("Similarity matrix between medoids:")
print(similarity_matrix)