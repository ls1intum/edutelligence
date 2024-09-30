from athena.modeling import Exercise, Submission
from module_modeling_llm.models.exercise_model import ExerciseModel
from module_modeling_llm.apollon_transformer.apollon_json_transformer import ApollonJSONTransformer


def get_exercise_model(exercise: Exercise, submission: Submission) -> ExerciseModel:

    serialized_example_solution = None
    if exercise.example_solution:
        serialized_example_solution, _, _ = ApollonJSONTransformer.transform_json(exercise.example_solution)

    transformed_submission, element_id_mapping, diagram_type = ApollonJSONTransformer.transform_json(submission.model)

    return ExerciseModel(
        submission_id=submission.id,
        exercise_id=exercise.id,
        transformed_submission=transformed_submission,
        problem_statement=exercise.problem_statement,
        max_points=exercise.max_points,
        bonus_points=exercise.bonus_points,
        grading_instructions=exercise.grading_instructions,
        submission_uml_type=diagram_type,
        transformed_example_solution=serialized_example_solution,
        element_id_mapping=element_id_mapping,
    )

    
