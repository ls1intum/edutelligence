from typing import List, Optional
from athena.modeling import Feedback
from athena.schemas.structured_grading_instruction import StructuredGradingInstructionGroup
from module_modeling_llm.models.assessment_model import AssessmentModel
from module_modeling_llm.models.exercise_model import ExerciseModel


def convert_to_athana_feedback_model(
        feedback_result : AssessmentModel, 
        exercise_model: ExerciseModel, 
        is_graded: bool,
        manual_structured_grading_instructions: Optional[List[StructuredGradingInstructionGroup]] = None
    ) -> List[Feedback]:
    
    grading_instruction_ids = set(
        grading_instruction.id
        for criterion in manual_structured_grading_instructions or []
        for grading_instruction in criterion.structured_grading_instructions
    )

    feedbacks = []
    for feedback in feedback_result.feedbacks:
        # Each feedback has a grading_instruction_id. However we only want to have the grading_instruction_id in the final feedback that are associated with the manual structured grading instructions
        grading_instruction_id = feedback.grading_instruction_id if feedback.grading_instruction_id in grading_instruction_ids else None
        element_ids = [exercise_model.element_id_mapping[element] for element in (feedback.element_names or [])]

        feedbacks.append(Feedback(
            exercise_id=exercise_model.exerciseId,
            submission_id=exercise_model.submissionId,
            title=feedback.title,
            description=feedback.description,
            element_ids=element_ids,
            credits=feedback.credits,
            structured_grading_instruction_id=grading_instruction_id,
            meta={},
            id=None,
            is_graded=is_graded
        ))

    return feedbacks