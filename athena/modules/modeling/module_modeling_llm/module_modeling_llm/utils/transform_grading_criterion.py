from typing import List, Optional

from athena.schemas.grading_criterion import GradingCriterion
from module_modeling_llm.models.grading_instruction_model import Criterion, GradingInstructionModel, GradingItem


def transform_grading_criterion(criteria: Optional[List[GradingCriterion]]) -> GradingInstructionModel:
    if not criteria:
        return GradingInstructionModel(total_points=0, items=[])

    total_points = 0
    all_items = []

    for criterion in criteria:
        criterion_points = sum(instr.credits for instr in criterion.structured_grading_instructions)
        total_points += criterion_points

        for instr in criterion.structured_grading_instructions:
            criterias = [
                Criterion(description=instr.instruction_description)
            ]
            
            item = GradingItem(
                id=criterion.id,
                name=criterion.title or instr.grading_scale,
                points=instr.credits,
                criteria=criterias
            )
            
            all_items.append(item)
    
    return GradingInstructionModel(
        total_points=total_points,
        items=all_items
    )
