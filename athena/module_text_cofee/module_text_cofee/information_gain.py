from typing import List
from athena.database import get_db
from athena.models.db_text_submission import DBTextSubmission
from athena.schemas.text_submission import TextSubmission
from module_text_cofee.models.db_text_block import DBTextBlock
from module_text_cofee.models.db_text_cluster import DBTextCluster


def calculate_information_gain(submission: TextSubmission, ungraded_submission_ids: List[int]):
    """
    Calculate the information gain for a submission.
    The submission with the highest information gain is the most useful to grade, so it should be graded first.
    It will be returned by the submission selection endpoint in the end.
    """
    information_gain = 0.0
    with get_db() as db:
        # The total information gain is calculated as the following sum:
        # (1) added distance / cluster size for each block
        # (2) "cluster percentage" = number indicating percentage of clusters with less text blocks on ungraded submissions
        all_clusters = db.query(DBTextBlock).filter(DBTextBlock.submission_id == submission.id).all()
        for block in all_clusters:
            # (1) added distance / cluster size for each block
            information_gain += block.calculate_added_distance() / len(block.cluster.blocks)
            # (2) "cluster percentage" = number indicating percentage of clusters with less text blocks on ungraded submissions
            number_of_clusters_with_less_ungraded_blocks = 0
            my_number_of_ungraded_blocks = block.cluster.get_number_of_ungraded_blocks(ungraded_submission_ids)
            for cluster in db.query(DBTextCluster).filter(block.cluster.__class__.exercise_id == block.cluster.exercise_id).all():
                # check if cluster has less ungraded blocks
                if cluster.get_number_of_ungraded_blocks(ungraded_submission_ids) < my_number_of_ungraded_blocks:
                    number_of_clusters_with_less_ungraded_blocks += 1
            information_gain += number_of_clusters_with_less_ungraded_blocks / len(all_clusters)
    return information_gain