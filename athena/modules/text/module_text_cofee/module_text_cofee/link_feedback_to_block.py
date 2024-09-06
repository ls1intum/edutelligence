"""
Text Feedbacks are not inherently linked to a text block.
This is because the feedbacks are just specified by a start and end index.
This means that a feedback can be given on a text block, but also on a part of a text block.
because of that, we need to link feedbacks to text blocks, to find out which feedbacks are given on which text blocks
more easily later on, when creating feedback suggestions.
"""
from typing import Optional

from athena.database import get_db
from athena.text import Feedback
from module_text_cofee.models.db_text_block import DBTextBlock


def feedback_to_text_block(feedback: Feedback) -> Optional[DBTextBlock]:
    """
    Returns the text block that the given feedback is given on, if any.
    """
    with get_db() as db:
        # get blocks of submission
        blocks = db.query(DBTextBlock).filter_by(submission_id=feedback.submission_id).all()
        # find block
        for block in blocks:
            if block.includes_feedback(feedback):
                return block
        return None


def link_feedback_to_block(feedback: Feedback):
    """
    Links the given feedback to the text block that it is given on, if any.
    Modifies the feedback in place.
    """
    block = feedback_to_text_block(feedback)
    if block:
        feedback.meta["block_id"] = block.id
