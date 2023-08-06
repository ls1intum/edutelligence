from typing import List, Iterable

from athena.database import get_db
from athena.logger import logger
from module_text_cofee.models.db_text_cluster import DBTextCluster
try:
    from module_text_cofee.protobuf import cofee_pb2
except ImportError:
    from typing import TYPE_CHECKING
    if TYPE_CHECKING:
        pass
    else:
        raise
from module_text_cofee.models.db_text_block import DBTextBlock


def store_text_blocks(segments: List[cofee_pb2.Segment], clusters: List[cofee_pb2.Cluster]):  # type: ignore
    """Convert segments to text blocks and store them in the DB."""
    for segment in segments:
        # store text block in DB
        with get_db() as db:
            model = DBTextBlock(
                id=segment.id,
                submission_id=segment.submissionId,
                text=segment.text,
                index_start=segment.startIndex,
                index_end=segment.endIndex,
                cluster_id=None,
            )
            db.merge(model)
            db.commit()


def store_text_clusters(exercise_id: int, clusters: Iterable[cofee_pb2.Cluster]) -> List[int]:  # type: ignore
    """Store text clusters in the DB. Returns the cluster IDs."""
    cluster_ids = []
    for cluster in clusters:
        distance_matrix: List[List[float]] = [[0.0 for _ in range(len(cluster.segments))] for _ in range(len(cluster.segments))]
        for entry in cluster.distanceMatrix:
            distance_matrix[entry.x][entry.y] = entry.value
        # store text cluster in DB
        with get_db() as db:
            model = DBTextCluster(
                exercise_id=exercise_id
            )
            model.distance_matrix = distance_matrix
            db.add(model)
            db.flush()
            cluster_ids.append(model.id)
            db.commit()
    return cluster_ids


def connect_text_blocks_to_clusters(clusters: List[cofee_pb2.Cluster], cluster_ids):  # type: ignore
    """
    Connect text blocks to clusters via the cluster_id field.
    Also store the positions of the text blocks in the clusters in the DB, in the same order that Athena-CoFee provides.
    This is necessary because the distance matrix is ordered in the same way. When we later the distance between
    two text blocks, we need to know their positions in the cluster because that's the place where we need to look 
    up the distance in the distance matrix.
    """
    for cluster, cluster_id in zip(clusters, cluster_ids):
        with get_db() as db:
            for i, segment in enumerate(cluster.segments):
                model = db.query(DBTextBlock).filter(DBTextBlock.id == segment.id).one()
                model.position_in_cluster = i
                model.cluster_id = cluster_id  # cannot use cluster.id because cluster is an object from Athena and we need the DB ID
                db.merge(model)
            db.commit()


def process_results(clusters: List[cofee_pb2.Cluster], segments: List[cofee_pb2.Segment], exercise_id):  # type: ignore
    """Processes results coming back from the CoFee system via callbackUrl"""
    logger.debug("Received %d clusters and %d segments from CoFee", len(clusters), len(segments))
    cluster_ids = store_text_clusters(exercise_id, clusters)
    logger.debug("Cluster IDs: %s", cluster_ids)
    store_text_blocks(segments, clusters)
    connect_text_blocks_to_clusters(clusters, cluster_ids)
    logger.debug("Finished processing CoFee results")
