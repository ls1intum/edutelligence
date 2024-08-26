import json
import os

from pydantic import ValidationError, parse_obj_as
from IPython.display import HTML, display

from module_text_llm.text_evaluation.evaluation_schemas import Exercise, Submission, Feedback


def process_file(file_data, exercise_id, technique, exercises, experiment_data):
    """Processes a single file's data, attempting to add it to exercises or deferring to experiment_data."""
    try:
        # Ensure feedbacks in each submission are properly structured
        for submission in file_data.get('submissions', []):
            if isinstance(submission.get('feedbacks'), list):
                submission['feedbacks'] = {technique: submission['feedbacks']}
            elif not isinstance(submission.get('feedbacks'), dict):
                submission['feedbacks'] = {technique: []}

        # Convert submissions and feedbacks to correct Pydantic models
        file_data['submissions'] = [parse_obj_as(Submission, sub) for sub in file_data.get('submissions', [])]

        # Attempt to create the Exercise object
        exercise = Exercise(**file_data)

        # Check if the exercise already exists in the list
        existing_exercise = next((ex for ex in exercises if ex.id == exercise_id), None)

        if existing_exercise:
            # Validate and update existing submissions
            exercises = validate_submissions(exercises, exercise_id, exercise)
            # Add new feedbacks to existing submissions
            exercises = add_feedbacks(exercises, exercise_id, exercise, technique)
        else:
            # New exercise, add to the list of exercises
            exercises.append(exercise)

    except ValidationError as e:
        # On validation error, store in experiment_data for later processing
        experiment_data.append((file_data, exercise_id, technique))

    return exercises, experiment_data


def validate_submissions(exercises, exercise_id, new_exercise):
    """Validates that submissions are the same between existing and new exercises."""
    existing_exercise = next(ex for ex in exercises if ex.id == exercise_id)
    if len(existing_exercise.submissions) != len(new_exercise.submissions):
        raise ValueError(f"Submissions count mismatch for exercise {existing_exercise.id}")
    for existing_sub, new_sub in zip(existing_exercise.submissions, new_exercise.submissions):
        if existing_sub.id != new_sub.id:
            raise ValueError(f"Submission ID mismatch for exercise {existing_exercise.id}")
    return exercises


def add_feedbacks(exercises, exercise_id, new_exercise, technique):
    """Adds feedbacks from a new exercise to an existing one."""
    existing_exercise = next(ex for ex in exercises if ex.id == exercise_id)
    for existing_sub, new_sub in zip(existing_exercise.submissions, new_exercise.submissions):
        if technique not in existing_sub.feedbacks:
            existing_sub.feedbacks[technique] = []
        existing_sub.feedbacks[technique].extend(new_sub.feedbacks.get(technique, []))
    return exercises


def process_experiment_data(experiment_data, exercises):
    """Processes all experiment data, adding feedbacks to existing exercises."""
    for file_data, exercise_id, technique in experiment_data:
        existing_exercise = next((ex for ex in exercises if ex.id == exercise_id), None)
        if not existing_exercise:
            raise ValueError(f"Exercise {exercise_id} not found for experiment data")

        # Ensure that submissions are correctly typed before processing
        file_data['submissions'] = [parse_obj_as(Submission, sub) for sub in file_data.get('submissions', [])]

        # Iterate over the submissions in the experiment data
        for submission_id, submission_data in file_data['submissionsWithFeedbackSuggestions'].items():
            existing_submission = next((sub for sub in existing_exercise.submissions if sub.id == int(submission_id)),
                                       None)

            if not existing_submission:
                raise ValueError(f"Submission ID {submission_id} not found in exercise {exercise_id}")

            # Add the suggestions to the existing feedbacks under the correct technique
            if technique not in existing_submission.feedbacks:
                existing_submission.feedbacks[technique] = []

            # Ensure feedbacks are correctly typed before adding them
            suggestions = parse_obj_as(list[Feedback], submission_data['suggestions'])
            existing_submission.feedbacks[technique].extend(suggestions)

    return exercises


def process_data(data):
    """Main processing function to handle all files."""
    exercises = []
    experiment_data = []

    # Process each file's data
    for exercise_id, technique, file_data in data:
        exercises, experiment_data = process_file(file_data, exercise_id, technique, exercises, experiment_data)

    # Process experiment data
    exercises = process_experiment_data(experiment_data, exercises)

    total_feedbacks = sum(len(sub.feedbacks) for ex in exercises for sub in ex.submissions)
    total_feedback_items = sum(
        len(feedbacks) for ex in exercises for sub in ex.submissions for feedbacks in sub.feedbacks.values())

    # Display a summary of processing
    summary_message = (
        f"<div style='color: green; font-weight: bold;'>Data Processing Completed!</div>"
        f"<div style='color: black;'>"
        f"Total exercises processed: <span style='color: blue;'>{len(exercises)}</span><br>"
        f"Total feedbacks processed: <span style='color: blue;'>{total_feedbacks}</span><br>"
        f"Total feedback items processed: <span style='color: blue;'>{total_feedback_items}</span>"
        f"</div>"
    )
    display(HTML(summary_message))

    return exercises  # Return the list of exercises


def remove_feedback_titles(directory):
    total_titles_replaced = 0

    def replace_titles_in_items(items):
        nonlocal total_titles_replaced
        for item in items:
            if isinstance(item, dict) and "title" in item:
                item["title"] = None
                total_titles_replaced += 1

    for filename in os.listdir(directory):
        if filename.endswith(".json"):
            file_path = os.path.join(directory, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)

            if isinstance(data, dict):
                # Handle submissions that might contain feedbacks or suggestions
                if "submissions" in data and isinstance(data["submissions"], list):
                    for submission in data["submissions"]:
                        # Replace titles in feedbacks
                        if "feedbacks" in submission and isinstance(submission["feedbacks"], list):
                            replace_titles_in_items(submission["feedbacks"])

                        # Replace titles in suggestions
                        if "suggestions" in submission and isinstance(submission["suggestions"], list):
                            replace_titles_in_items(submission["suggestions"])

                # Handle other possible structures that might contain feedbacks or suggestions
                if "submissionsWithFeedbackSuggestions" in data and isinstance(data["submissionsWithFeedbackSuggestions"], dict):
                    for submission_id, submission_data in data["submissionsWithFeedbackSuggestions"].items():
                        if "feedbacks" in submission_data and isinstance(submission_data["feedbacks"], list):
                            replace_titles_in_items(submission_data["feedbacks"])
                        if "suggestions" in submission_data and isinstance(submission_data["suggestions"], list):
                            replace_titles_in_items(submission_data["suggestions"])

            with open(file_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False, indent=4)

    # Displaying the success message
    summary_message = (
            f"<div style='color: green; font-weight: bold;'>"
            f"Success! {total_titles_replaced} title(s) processed.</div>"
    )
    display(HTML(summary_message))
