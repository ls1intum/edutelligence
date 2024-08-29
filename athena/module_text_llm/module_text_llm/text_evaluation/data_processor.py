import json
import os
from IPython.display import display, HTML

from athena import GradingCriterion, ExerciseType
from athena.schemas import TextLanguageEnum
from module_text_llm.text_evaluation.evaluation_schemas import Exercise, Submission, Feedback, Assessment


def process_dump_data(exercise_id: int, technique: str, data: dict) -> Exercise:
    grading_criteria = [GradingCriterion(**criterion) for criterion in data.get("grading_criteria", [])]

    submissions = [
        Submission(
            id=submission["id"],
            exercise_id=exercise_id,
            text=submission["text"],
            language=TextLanguageEnum(submission["language"]) if "language" in submission else None,
            assessments=[
                Assessment(
                    id=technique,
                    feedbacks=[
                        Feedback(**{**feedback, "title": None}) for feedback in submission.get("feedbacks", [])
                    ]
                )
            ]
        ) for submission in data.get("submissions", [])
    ]

    exercise = Exercise(
        id=exercise_id,
        title=data["title"],
        type=ExerciseType(data["type"]),
        max_points=data["max_points"],
        bonus_points=data["bonus_points"],
        grading_instructions=data.get("grading_instructions"),
        grading_criteria=grading_criteria,
        problem_statement=data["problem_statement"],
        example_solution=data.get("example_solution"),
        submissions=submissions
    )

    return exercise


def add_assessments_to_submissions(exercise: Exercise, data: dict, assessment_id: str) -> Exercise:
    existing_submissions = {submission.id: submission for submission in exercise.submissions}

    for submission_id, feedback_data in data.get("submissionsWithFeedbackSuggestions", {}).items():
        submission_id = int(submission_id)

        if submission_id not in existing_submissions:
            raise ValueError(f"Submission with ID {submission_id} does not exist in the provided exercise.")

        assessment = Assessment(
            id=assessment_id,
            feedbacks=[Feedback(**{**suggestion, "title": None}) for suggestion in feedback_data.get("suggestions", [])]
        )

        # Add the assessment to the existing submission
        existing_submissions[submission_id].assessments.append(assessment)

    return exercise

def process_data(data) -> list[Exercise]:
    """Function for processing the data into the evaluation schema.

    Parameters:
    - data: List of tuples, where each tuple contains (exercise_id, technique, file_data).
    """
    exercises = []

    # 1. Process the data (i.e. from database dump) and create exercises
    for exercise_id, technique, file_data in data:
        is_experiment = file_data.get("experimentId") is not None
        if not is_experiment:
            exercise = process_dump_data(exercise_id, technique, file_data)
            exercises.append(exercise)

    # 2. Process the data (i.e. from experiments) and add assessments to submissions
    # The second step is necessary because experiment data does not contain the full exercise and submission information
    existing_exercises = {exercise.id: exercise for exercise in exercises}
    for exercise_id, technique, file_data in data:
        is_experiment = file_data.get("experimentId") is not None
        if is_experiment:
            if exercise_id not in existing_exercises:
                raise ValueError(f"Exercise with ID {exercise_id} does not exist in the provided data.")
            add_assessments_to_submissions(existing_exercises[exercise_id], file_data, technique)

    # Display a summary of processing
    num_exercises = len(exercises)
    num_submissions = sum(len(exercise.submissions) for exercise in exercises)
    num_assessments = sum(len(submission.assessments) for exercise in exercises for submission in exercise.submissions)
    num_feedbacks = sum(len(assessment.feedbacks) for exercise in exercises for submission in exercise.submissions for assessment in submission.assessments)

    summary_message = (
        f"<div style='color: green; font-weight: bold;'>Data Processing Completed!</div>"
        f"<div style='color: black;'>"
        f"Total exercises processed: <span style='color: blue;'>{num_exercises}</span><br>"
        f"Total submissions processed: <span style='color: blue;'>{num_submissions}</span><br>"
        f"Total assessments processed: <span style='color: blue;'>{num_assessments}</span><br>"
        f"Total feedbacks processed: <span style='color: blue;'>{num_feedbacks}</span>"
        f"</div>"
    )
    display(HTML(summary_message))

    return exercises
