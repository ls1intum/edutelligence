import matplotlib.pyplot as plt
import numpy as np
from fastapi import APIRouter, Depends, Response, status
from matplotlib.patches import Patch
from scipy.spatial import ConvexHull
from scipy.spatial.qhull import QhullError

from atlasml.clients.weaviate import get_weaviate_client, CollectionNames
from atlasml.dependencies import TokenValidator
from atlasml.ml.Clustering.HDBSCAN import apply_hdbscan
from atlasml.ml.Clustering.TSNE import apply_tsne
from atlasml.ml.VectorEmbeddings import FallbackModel
from atlasml.ml.MLPipelines.PipelineWorkflows import PipelineWorkflows
from atlasml.models.competency import (
    Competency,
    GenerateCompetencyRequest,
    GenerateCompetencyRequestBatch,
    GenerateEmbeddingsResponse,
    SaveCompetencyRequest,
    SuggestCompetencyRequest,
    SuggestCompetencyResponse,
)

router = APIRouter(prefix="/api/v1/competency", tags=["competency"])


@router.post("/generate-embeddings", response_model=GenerateEmbeddingsResponse)
async def generate_embeddings(request: GenerateCompetencyRequest):
    print("GENERATING EMBEDDING FOR ==> ", request.id)
    uuid, embeddings = FallbackModel.generate_embeddings(request.id, request.description)

    print("EMBEDDING GENERATED WITH UUID ==> ", uuid)
    print("EMBEDDING's VECTOR LENGTH ==> ", len(embeddings))

    return GenerateEmbeddingsResponse(embeddings=[])


@router.post("/generate-embeddings-batch", response_model=GenerateEmbeddingsResponse)
async def generate_embeddings_batch(request: GenerateCompetencyRequestBatch):
    response = []
    for req in request.competencies:
        print("GENERATING EMBEDDING FOR ==> ", req.id)
        embeddings = FallbackModel.generate_embeddings(req.id, req.description)
        response.append(embeddings)
        print("EMBEDDING GENERATED")
    print("EMBEDING ARE HERE ==> ", len(response))

    return GenerateEmbeddingsResponse(embeddings=response)


@router.get("/competency/{id}", response_model=Competency)
async def get_competency(id: str):
    weaviate_client = get_weaviate_client()
    competency_embeddings = weaviate_client.get_all_embeddings()

    print("COMPETENCY EMBEDDINGS LENGTH: ", len(competency_embeddings))
    print("Generating Cluster Plot...")

    vector_data = np.array(
        [embedding["vector"]["default"] for embedding in competency_embeddings]
    )
    data_ids = np.array([embedding["id"] for embedding in competency_embeddings])

    # Apply t-SNE with 2 components for 2D visualization
    tsne_result = apply_tsne(vector_data, n_components=2, perplexity=5)

    # Cluster the t-SNE result using HDBSCAN
    labels = apply_hdbscan(
        tsne_result, eps=0.01, min_samples=1, metric="cosine", min_cluster_size=4
    )

    # Build clusters dictionary: label -> { 'center': cluster center, 'data_ids': list of data ids }
    clusters = {}
    for cluster in np.unique(labels):
        indices = np.where(labels == cluster)[0]
        cluster_points = tsne_result[indices]
        center_point = np.mean(cluster_points, axis=0)
        cluster_data_ids = list(data_ids[indices])
        clusters[cluster] = {"center": center_point, "data_ids": cluster_data_ids}

    plt.figure()
    cmap = plt.get_cmap("tab10")
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
                hull = ConvexHull(cluster_points, qhull_options="QJ")
                hull_points = cluster_points[hull.vertices]
                hull_points = np.concatenate([hull_points, hull_points[:1]], axis=0)
                plt.fill(hull_points[:, 0], hull_points[:, 1], color=color, alpha=0.3)
            except QhullError as e:
                print(f"⚠️ Could not compute ConvexHull for cluster {cluster}: {e}")

        # Plot the unique cluster center using the pre-computed clusters dictionary
        center = clusters[cluster]["center"]
        plt.scatter(center[0], center[1], color=color, marker="X", s=100)

        # Append a legend entry for this cluster
        legend_handles.append(Patch(color=color, label=f"Cluster {cluster}"))

    plt.title("Cluster Centers and Background Areas")
    plt.xlabel("Component 1")
    plt.ylabel("Component 2")
    plt.legend(handles=legend_handles)
    plt.show()


@router.get("/exercise/all", response_model=list[dict])
async def get_all_exercises():
    weaviate_client = get_weaviate_client()
    exercises = weaviate_client.get_all_embeddings(CollectionNames.EXERCISE.value)
    return exercises

@router.get("/embedings", response_model=list[dict])
async def get_all_competencies():
    weaviate_client = get_weaviate_client()
    competencies = weaviate_client.get_all_embeddings(CollectionNames.COMPETENCY.value)
    return competencies

@router.get("/clusters", response_model=list[str])
async def get_clusters():
    weaviate_client = get_weaviate_client()
    clusters = weaviate_client.get_all_embeddings(CollectionNames.CLUSTERCENTER.value)
    return [cluster['properties']['label_id'] for cluster in clusters ]

@router.get("/delete_embedings/{collection_name}", response_model=list[dict])
async def delete_embedings(collection_name: str):
    weaviate_client = get_weaviate_client()
    weaviate_client.delete_all_data_from_collection(CollectionNames[collection_name].value)
    return Response(status_code=status.HTTP_200_OK, content=b"[]", media_type="application/json")


@router.post(
    "/suggest",
    response_model=SuggestCompetencyResponse,
    dependencies=[Depends(TokenValidator())],
)
async def suggest_competencies(request: SuggestCompetencyRequest):
    pipeline = PipelineWorkflows()
    competency = pipeline.newTextPipeline(request.description)
    return SuggestCompetencyResponse(
        competencies=[competency],
        competency_relations=[]
    )


@router.post(
    "/save", response_model=dict, dependencies=[Depends(TokenValidator())]
)
async def save_competencies(request: SaveCompetencyRequest):
    # TODO: @ArdaKaraman call required pipeline with the input you do not need to return anything
    # TODO: For test purposes you can delete TokenValidator() from dependencies
    return Response(
        status_code=status.HTTP_200_OK,
        content=b"[]",
        media_type="application/json",
    )
