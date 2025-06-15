import pytest
from athena.modeling import Exercise, Submission
from athena.schemas.exercise_type import ExerciseType
from module_modeling_llm.utils.get_exercise_model import get_exercise_model
from module_modeling_llm.core.get_structured_grading_instructions import get_structured_grading_instructions
from module_modeling_llm.core.generate_suggestions import generate_suggestions
from test_data.ecommerce_data import (
    ECOMMERCE_GRADING_CRITERIA,
    ECOMMERCE_PROBLEM_STATEMENT,
    ECOMMERCE_GRADING_INSTRUCTIONS,
    ECOMMERCE_EXAMPLE_SOLUTION,
    ECOMMERCE_SUBMISSION
)
from test_data.hospital_data import (
    HOSPITAL_GRADING_CRITERIA,
    HOSPITAL_PROBLEM_STATEMENT,
    HOSPITAL_GRADING_INSTRUCTIONS,
    HOSPITAL_EXAMPLE_SOLUTION,
    HOSPITAL_SUBMISSION
)

@pytest.mark.asyncio
async def test_sgi_ecommerce_system(real_config):
    """Test the grading of various UML diagram elements in an e-commerce system."""
    # Setup exercise and submission
    exercise = Exercise(
        id=10,
        title="E-commerce UML",
        type=ExerciseType.modeling,
        max_points=10,
        bonus_points=0,
        grading_instructions=ECOMMERCE_GRADING_INSTRUCTIONS,
        problem_statement=ECOMMERCE_PROBLEM_STATEMENT,
        example_solution=ECOMMERCE_EXAMPLE_SOLUTION,
        grading_criteria=ECOMMERCE_GRADING_CRITERIA
    )
    submission = Submission(
        id=10,
        exerciseId=exercise.id,
        model=ECOMMERCE_SUBMISSION
    )
    
    # Get feedback
    exercise_model = get_exercise_model(exercise, submission)
    structured_grading_instructions = await get_structured_grading_instructions(
        exercise_model, real_config, exercise.grading_instructions, exercise.grading_criteria, debug=False
    )
    feedback = await generate_suggestions(
        exercise_model, structured_grading_instructions, real_config, debug=False
    )
    
    # Check all criteria
    credits_by_id = {f.grading_instruction_id: f.credits for f in feedback.feedbacks}
    assert credits_by_id[1] == 0.0, "User.email is missing"
    assert credits_by_id[2] == 0.0, "Order-Product should be association, not composition"
    assert credits_by_id[3] == 2.0, "Cart-Product composition is correct"
    assert credits_by_id[4] == 2.0, "User-Address aggregation is correct"
    assert credits_by_id[5] == 0.0, "Order->Cart inheritance is missing"

@pytest.mark.asyncio
async def test_sgi_hospital_management(real_config):
    """Test the grading of various UML diagram elements in a hospital management system."""
    # Setup exercise and submission
    exercise = Exercise(
        id=1,
        title="Hospital Management System Design",
        type=ExerciseType.modeling,
        max_points=10,
        bonus_points=0,
        grading_instructions=HOSPITAL_GRADING_INSTRUCTIONS,
        problem_statement=HOSPITAL_PROBLEM_STATEMENT,
        example_solution=HOSPITAL_EXAMPLE_SOLUTION,
        grading_criteria=HOSPITAL_GRADING_CRITERIA
    )

    submission = Submission(
        id=1,
        exerciseId=exercise.id,
        model=HOSPITAL_SUBMISSION
    )

    # Get feedback
    exercise_model = get_exercise_model(exercise, submission)
    structured_grading_instructions = await get_structured_grading_instructions(
        exercise_model, real_config, exercise.grading_instructions, exercise.grading_criteria, debug=False
    )
    feedback = await generate_suggestions(
        exercise_model, structured_grading_instructions, real_config, debug=False
    )

    # Check all criteria
    credits_by_id = {f.grading_instruction_id: f.credits for f in feedback.feedbacks}
    print(credits_by_id)
    assert credits_by_id[1] == 0.0, "Appointment class is missing date and status attributes"
    assert credits_by_id[2] >= 1.0, "Doctor must inherit from Person"
    assert credits_by_id[4] == 0.0, "Patient has patientId and medicalHistory attributes"
    assert credits_by_id[5] == 0.0, "Department-Staff should be composition" 