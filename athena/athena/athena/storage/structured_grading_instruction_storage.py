from typing import Optional
from athena.contextvars import get_lms_url
from athena.database import get_db
from athena.schemas.structured_grading_instruction import StructuredGradingInstruction

def get_stored_structured_grading_instruction(exercise_id: int, cache_key: str, lms_url: Optional[str] = None) -> Optional[StructuredGradingInstruction]:
    if lms_url is None:
        lms_url = get_lms_url()

    db_structured_grading_criterion_cls = StructuredGradingInstruction.get_model_class()
    with get_db() as db:
        db_criterion = db.query(db_structured_grading_criterion_cls).filter_by(
            exercise_id=exercise_id, 
            cache_key=cache_key,
            lms_url=lms_url
        ).first()
        return db_criterion.to_schema() if db_criterion else None

def store_structured_grading_instruction(criterion: StructuredGradingInstruction, lms_url: Optional[str] = None) -> StructuredGradingInstruction:
    if lms_url is None:
        lms_url = get_lms_url()

    db_criterion = criterion.to_model()
    db_criterion.lms_url = lms_url

    with get_db() as db:
        db.merge(db_criterion)
        db.commit()
        db.refresh(db_criterion)

    return db_criterion.to_schema()