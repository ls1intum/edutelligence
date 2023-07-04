import struct
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
        cluster_id = None
        for cluster in clusters:
            for s in cluster.segments:
                if s.id == segment.id:
                    cluster_id = cluster.treeId
                    break
        if cluster_id is None:
            logger.warning("Segment %d has no cluster", segment.id)
        # store text block in DB
        with get_db() as db:
            model = DBTextBlock(
                id=segment.id,
                submission_id=segment.submissionId,
                text=segment.text,
                index_start=segment.startIndex,
                index_end=segment.endIndex,
                cluster_id=cluster_id,
            )
            db.merge(model)
            db.commit()


def float_matrix_to_bytes(floats: List[List[float]]) -> bytes:
    """Convert a matrix of floats to a bytes object."""
    return struct.pack(f"{len(floats) * len(floats[0])}f", *sum(floats, []))


def store_text_clusters(exercise_id: int, clusters: Iterable[cofee_pb2.Cluster]):  # type: ignore
    """"""
    for cluster in clusters:
        distance_matrix: List[List[float]] = [[0.0 for _ in range(len(cluster.segments))] for _ in range(len(cluster.segments))]
        for entry in cluster.distanceMatrix:
            distance_matrix[entry.x][entry.y] = entry.value
        # store text cluster in DB
        with get_db() as db:
            model = DBTextCluster(
                id=cluster.treeId,
                exercise_id=exercise_id
            )
            model.distance_matrix = distance_matrix
            db.merge(model)
            db.commit()


def process_results(clusters: List[cofee_pb2.Cluster], segments: List[cofee_pb2.Segment], exercise_id):  # type: ignore
    """Processes results coming back from the CoFee system via callbackUrl"""
    logger.debug("Received %d clusters and %d segments from CoFee", len(clusters), len(segments))
    store_text_blocks(segments, clusters)
    store_text_clusters(exercise_id, clusters)
    logger.debug("Finished processing CoFee results")
