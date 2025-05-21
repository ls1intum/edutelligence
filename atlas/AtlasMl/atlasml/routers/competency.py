from fastapi import APIRouter
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from scipy.spatial import ConvexHull
import numpy as np

from atlasml.models.competency import GenerateCompetencyRequest, Competency, GenerateEmbedingsResponse, GenerateCompetencyRequestBatch

from atlasml.ml.VectorEmbeddings import FallbackModel
from atlasml.ml.Clustering.TSNE import apply_tsne
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan

from atlasml.clients.weaviate import get_weaviate_client

router = APIRouter()

@router.post("/generate-embedings", response_model=GenerateEmbedingsResponse)
async def generate_embedings(request: GenerateCompetencyRequest):
    print("GENERATING EMBEDDING FOR ==> ", request.id)
    uuid, embedings = FallbackModel.generate_embeddings_local(request.id, request.description)

    print("EMBEDDING GENERATED WITH UUID ==> ", uuid)
    print("EMBEDDING's VECTOR LENGTH ==> ", len(embedings))

    return GenerateEmbedingsResponse(
        embedings=[]
    )

@router.post("/generate-embedings-batch", response_model=GenerateEmbedingsResponse)
async def generate_embedings_batch(request: GenerateCompetencyRequestBatch):
    response = []
    for req in request.competencies:
        print("GENERATING EMBEDDING FOR ==> ", req.id)
        embedings = FallbackModel.generate_embeddings_local(req.id, req.description)
        response.append(embedings)
        print("EMBEDDING GENERATED")
    print("EMBEDING ARE HERE ==> ", len(response))

    return GenerateEmbedingsResponse(
        embedings=response
    )


@router.get("/competency/{id}", response_model=Competency)
async def get_competency(id: str):
    weaviate_client = get_weaviate_client()
    competency_embeddings = weaviate_client.get_all_embeddings()
    
    print("COMPETENCY EMBEDDINGS LENGTH: ", len(competency_embeddings))
    print("Generating Cluster Plot...")
    
    vector_data = np.array([
        embedding["vector"]["default"]
        for embedding in competency_embeddings
    ])
    data_ids = np.array([
        embedding["id"]
        for embedding in competency_embeddings
    ])

    # Apply t-SNE with 2 components for 2D visualization
    tsne_result = apply_tsne(vector_data, n_components=2, perplexity=5)

    # Cluster the t-SNE result using HDBSCAN
    labels = apply_hdbscan(tsne_result, eps=0.01, min_samples=1, metric='cosine', min_cluster_size=4)

    # Build clusters dictionary: label -> { 'center': cluster center, 'data_ids': list of data ids }
    clusters = {}
    for cluster in np.unique(labels):
        indices = np.where(labels == cluster)[0]
        cluster_points = tsne_result[indices]
        center_point = np.mean(cluster_points, axis=0)
        cluster_data_ids = list(data_ids[indices])
        clusters[cluster] = {'center': center_point, 'data_ids': cluster_data_ids}

    plt.figure()
    cmap = plt.get_cmap('tab10')
    unique_labels = np.unique(labels)
    legend_handles = []
    # Loop through each cluster and fill the convex hull area and mark the center
    for idx, cluster in enumerate(unique_labels):
        # Get indices and points for the current cluster
        indices = np.where(labels == cluster)[0]
        cluster_points = tsne_result[indices]

        # Choose a color from the colormap (cycling if necessary)
        color = cmap(idx % 10)

        # If the cluster has enough points, compute and fill the convex hull area
        if cluster_points.shape[0] >= 3:
            try:
                hull = ConvexHull(cluster_points, qhull_options='QJ')
                hull_points = cluster_points[hull.vertices]
                hull_points = np.concatenate([hull_points, hull_points[:1]], axis=0)
                plt.fill(hull_points[:, 0], hull_points[:, 1], color=color, alpha=0.3)
            except QhullError as e:
                print(f"⚠️ Could not compute ConvexHull for cluster {cluster}: {e}")


        # Plot the unique cluster center using the pre-computed clusters dictionary
        center = clusters[cluster]['center']
        plt.scatter(center[0], center[1], color=color, marker='X', s=100)

        # Append a legend entry for this cluster
        legend_handles.append(Patch(color=color, label=f'Cluster {cluster}'))

    plt.title("Cluster Centers and Background Areas")
    plt.xlabel("Component 1")
    plt.ylabel("Component 2")
    plt.legend(handles=legend_handles)
    plt.show()

    return None
