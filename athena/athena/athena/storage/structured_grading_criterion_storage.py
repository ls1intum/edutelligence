from typing import Optional
from athena.contextvars import get_lms_url
from athena.database import get_db

from athena.models import DBStructuredGradingCriterion
from athena.schemas import StructuredGradingCriterion

def get_structured_grading_criterion(exercise_id: int, current_hash: Optional[str] = None) -> Optional[StructuredGradingCriterion]:
    lms_url = get_lms_url()
    with get_db() as db:
        cache_entry = db.query(DBStructuredGradingCriterion).filter(
            DBStructuredGradingCriterion.exercise_id == exercise_id,
            DBStructuredGradingCriterion.exercise.has(lms_url=lms_url)
        ).first()
        if cache_entry is not None and (current_hash is None or cache_entry.instructions_hash == current_hash):  # type: ignore
            return StructuredGradingCriterion.model_validate(cache_entry.structured_grading_criterion)
    return None

def store_structured_grading_criterion(
    exercise_id: int, hash: str, structured_instructions: StructuredGradingCriterion
):
    with get_db() as db:
        db.merge(
            DBStructuredGradingCriterion(
                exercise_id=exercise_id,
                instructions_hash=hash,
                structured_grading_criterion=structured_instructions.model_dump(),
            )
        )
        db.commit()
