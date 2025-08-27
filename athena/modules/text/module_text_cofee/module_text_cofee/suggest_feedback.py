from typing import List, Iterable

from athena.database import get_db
from athena.logger import logger
from athena.text import Submission, Feedback
from athena.helpers.text import get_exercise_feedbacks
from module_text_cofee.models.db_text_block import DBTextBlock
from module_text_cofee.models.db_text_cluster import DBTextCluster


DISTANCE_THRESHOLD = 1.0


def filter_feedbacks_by_block(feedbacks: List[Feedback], block: DBTextBlock) -> Iterable[Feedback]:
    """
    Filter a list of feedback to only contain feedback that is linked to a given block.
    """
    return (
        f for f in feedbacks
        if block.feedback_is_linked_to_block(f)
    )


def suggest_feedback_for_block(submission: Submission, block: DBTextBlock) -> List[Feedback]:
    """
    Suggest feedback for a text block (part of submission) based on existing feedback & processed clusters.
    """
    # Find the cluster that this block belongs to
    cluster = block.cluster
    if not cluster:
        logger.warning("Block %s has no cluster", block.id)
        return []
    # If the cluster is disabled, there should be no suggestions
    if cluster.disabled:
        return []
    # Get all blocks of that cluster
    blocks = cluster.blocks
    # Only consider blocks for which there is feedback available at all
    exercise_feedbacks = get_exercise_feedbacks(submission.exercise_id)
    blocks_with_feedback = [
        block
        for block in blocks
        if any(filter_feedbacks_by_block(exercise_feedbacks, block))
    ]
    if not blocks_with_feedback:
        logger.info("No feedback available for cluster %d", cluster.id)
        return []
    # Find the closest block to this block
    closest_block = min(
        blocks_with_feedback,
        key=lambda other_block: block.distance_to(other_block),
    )
    # If the distance is too large, there should be no suggestions
    if block.distance_to(closest_block) >= DISTANCE_THRESHOLD:
        return []
    # Get all feedbacks on the closest block
    closest_block_feedback = filter_feedbacks_by_block(exercise_feedbacks, closest_block)
    # add new submission ID, link the feedback to the block and add meta information for debugging
    suggested_feedback: List[Feedback] = []
    for f in closest_block_feedback:
        copy = f.model_copy(deep=True)
        copy.submission_id = submission.id
        copy.meta = {
            **copy.meta,
            "block_id": block.id,
            "original_submission_id": submission.id,
            "original_block_id": closest_block.id,
        }
        # adapt index numbers to new text block
        copy.index_start = block.index_start  # type: ignore
        copy.index_end = block.index_end  # type: ignore
        suggested_feedback.append(copy)
    return suggested_feedback


def suggest_feedback_for_submission(submission: Submission) -> List[Feedback]:
    """
    Suggest feedback for a submission based on existing feedback & processed clusters.
    """
    with get_db() as db:
        # get blocks of submission
        blocks = db.query(DBTextBlock).filter_by(submission_id=submission.id).all()
        # merge suggestions for all blocks
        return [
            suggestion
            for block in blocks
            for suggestion in suggest_feedback_for_block(submission, block)
        ]
