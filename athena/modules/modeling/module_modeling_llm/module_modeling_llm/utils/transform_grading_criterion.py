from athena.schemas.grading_criterion import GradingCriterion
from module_modeling_llm.module_modeling_llm.models.grading_instruction_model import Criterion, GradingInstructionModel, GradingItem

def transform_grading_criterion(criterion: GradingCriterion) -> GradingInstructionModel:
    total_points = sum(instr.credits for instr in criterion.structured_grading_instructions)
    
    items = []
    for instr in criterion.structured_grading_instructions:
        criteria = [
            Criterion(description=instr.instruction_description)
        ]
        
        item = GradingItem(
            id=instr.id,
            name=instr.grading_scale,
            points=instr.credits,
            criteria=criteria
        )
        
        items.append(item)
    
    return GradingInstructionModel(
        total_points=total_points,
        items=items
    )