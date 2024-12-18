import json
import os
from typing import List, Dict, Union

import numpy as np
import pandas as pd

from evaluation.model.model import Exercise, Feedback, Submission, GradingCriterion, StructuredGradingInstruction


def validate_columns(df: pd.DataFrame, required_columns: List[str]) -> None:
    """
    Validates that the given DataFrame contains the required columns.
    """
    missing_columns = set(required_columns) - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"A DataFrame is missing required columns: {', '.join(missing_columns)}.\n"
            f"Expected columns: {', '.join(required_columns)}.\n"
            f"Available columns: {', '.join(df.columns)}."
        )

def get_columns_from_dataframe(df: pd.DataFrame, rename_map: Dict[str, str], columns: List[str] = None) -> pd.DataFrame:
    """
    Extracts and renames columns from a DataFrame, replacing NaN values with None.
    """
    if columns is None:
        columns = list(rename_map.keys())

    validate_columns(df, columns)

    return df[columns].rename(columns=rename_map).replace({pd.NA: None, np.nan: None}).drop_duplicates()

def group_exercise_data(df: pd.DataFrame, feedback_type_filter: str = None) -> List[Exercise]:
    """
    Groups exercises, submissions, grading instructions, and feedback of specified type into a structured format.

    Args:
        df (pd.DataFrame): The DataFrame containing all exercise data.
        feedback_type_filter (str, optional): The feedback type to include (e.g., "LLM"). Defaults to "Tutor".

    Returns:
        List[Exercise]: A list of Exercise objects.
    """

    def process_feedbacks(exercise_id: int, submission_id: int) -> Union[List[Feedback], Dict[str, List[Feedback]]]:
        """Process feedbacks for a submission."""
        feedback_columns_map = {
            "feedback_id": "id", "feedback_text": "title", "feedback_detail_text": "description", "feedback_credits": "credits",
            "text_block_start_index": "index_start", "text_block_end_index": "index_end", "feedback_grading_instruction_id": "structured_grading_instruction_id",
            "exercise_id": "exercise_id", "submission_id": "submission_id"
        }
        filtered_df = df[(df["exercise_id"] == exercise_id) & (df["submission_id"] == submission_id) & (df["feedback_id"].notnull())]
        if feedback_type_filter:
            filtered_df = filtered_df[filtered_df["feedback_type"] == feedback_type_filter]

        feedback_data = get_columns_from_dataframe(filtered_df, feedback_columns_map, list(feedback_columns_map.keys()) + ["feedback_type"])
        feedback_data = feedback_data.sort_values(by=["index_start"], na_position="last")

        if feedback_type_filter:  # Return a list of Feedback objects for a single type
            return [Feedback(**row) for row in feedback_data.drop("feedback_type", axis=1).to_dict(orient="records")]

        categorized_feedback = {} # Return a dictionary of feedback lists for all types
        for feedback_type, group in feedback_data.groupby("feedback_type"):
            categorized_feedback[str(feedback_type)] = [
                Feedback(**row) for row in group.drop("feedback_type", axis=1).to_dict(orient="records")
            ]

        return categorized_feedback

    def process_submissions(exercise_id: int) -> List[Submission]:
        """Process submissions for an exercise."""
        submission_columns_map = {
            "submission_id": "id", "submission_text": "text"
        }

        filtered_df = df[(df["exercise_id"] == exercise_id) & (df["submission_id"].notnull())]
        submission_data = get_columns_from_dataframe(filtered_df, submission_columns_map)

        return [Submission(**row, language="ENGLISH", feedbacks=process_feedbacks(exercise_id, row["id"])) for row in submission_data.to_dict(orient="records")]

    def process_grading_instructions(exercise_id: int, criterion_id: int) -> List[StructuredGradingInstruction]:
        """Process grading instructions for a grading criterion."""
        instruction_columns_map = {
            "grading_instruction_id": "id", "grading_instruction_credits": "credits", "grading_instruction_grading_scale": "grading_scale",
            "grading_instruction_instruction_description": "instruction_description", "grading_instruction_feedback": "feedback",
            "grading_instruction_usage_count": "usage_count"
        }
        filtered_df = df[(df["exercise_id"] == exercise_id) & (df["grading_criterion_id"] == criterion_id) & (df["grading_instruction_id"].notnull())]
        instruction_data = get_columns_from_dataframe(filtered_df, instruction_columns_map)

        return [StructuredGradingInstruction(**row) for row in instruction_data.to_dict(orient="records")]

    def process_grading_criteria(exercise_id: int) -> List[GradingCriterion]:
        """Process grading criteria for an exercise."""
        criterion_columns_map = {
            "grading_criterion_id": "id", "grading_criterion_title": "title"
        }
        filtered_df = df[(df["exercise_id"] == exercise_id) & (df["grading_criterion_id"].notnull())]
        criterion_data = get_columns_from_dataframe(filtered_df, criterion_columns_map)

        return [GradingCriterion(**row, structured_grading_instructions=process_grading_instructions(exercise_id, row["id"])) for row in criterion_data.to_dict(orient="records")]

    exercise_columns_map = {
        "exercise_id": "id", "exercise_title": "title", "exercise_max_points": "max_points", "exercise_bonus_points": "bonus_points",
        "exercise_grading_instructions": "grading_instructions", "exercise_problem_statement": "problem_statement", "exercise_example_solution": "example_solution"
    }

    filtered_df = df[(df["exercise_id"].notnull())]
    exercise_data = get_columns_from_dataframe(filtered_df, exercise_columns_map)

    return [Exercise(**row, submissions=process_submissions(row["id"]), grading_criteria=process_grading_criteria(row["id"])) for row in exercise_data.to_dict(orient="records")]


def exercises_to_json(exercises: List[Exercise], output_path: str):
    """Converts a list of Exercise objects to JSON files."""
    os.makedirs(output_path, exist_ok=True)
    for exercise in exercises:
        file_path = os.path.join(output_path, f"exercise-{exercise.id}.json")
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(exercise.to_dict(), file, indent=4)


def read_result_files_to_dataframe(results_dir: str) -> pd.DataFrame:
    """Reads result JSON files from the specified directory and returns a flat DataFrame."""
    feedback_records = []

    file_paths = []
    for root, dirs, files in os.walk(results_dir):
        for file in files:
            if file.endswith(".json") and file.startswith("text_results_"):
                file_paths.append(os.path.join(root, file))

    if not file_paths:
        raise ValueError(f"No files with name text_results_<...> of type json were found in directory: {results_dir}.")

    for file_path in file_paths:
        filename = os.path.basename(file_path)  # Extract only the filename
        feedback_type = filename.split("_")[2]  # Perform split on the filename only

        with open(file_path, "r", encoding="utf-8") as file:
            result_data = json.load(file)
            submissions = result_data.get("submissionsWithFeedbackSuggestions", {})
            for submission_id, submission_data in submissions.items():
                for suggestion in submission_data.get("suggestions", []):
                    feedback_records.append({
                        "feedback_id": suggestion["id"],
                        "feedback_text": suggestion.get("title"),
                        "feedback_detail_text": suggestion["description"],
                        "feedback_credits": suggestion["credits"],
                        "feedback_grading_instruction_id": suggestion.get("structured_grading_instruction_id"),
                        "text_block_start_index": suggestion.get("index_start"),
                        "text_block_end_index": suggestion.get("index_end"),
                        "feedback_type": feedback_type,
                        "exercise_id": suggestion["exercise_id"],
                        "submission_id": suggestion["submission_id"],
                    })
    return pd.DataFrame(feedback_records)


def add_feedback_suggestions_to_data(data: pd.DataFrame, feedback_suggestions: pd.DataFrame) -> pd.DataFrame:
    """
    Adds feedback suggestions to the existing data, ensuring no duplicate feedback suggestions are added.

    Args:
        data (pd.DataFrame): The original data containing valid exercise and submission data.
        feedback_suggestions (pd.DataFrame): The feedback suggestions to be associated.

    Returns:
        pd.DataFrame: A DataFrame containing the combined data and feedback suggestions.

    Raises:
        ValueError: If the feedback suggestions contain overlapping entries or IDs not found in the existing data.
    """
    # Required columns
    data_required_columns = ["exercise_id", "submission_id"]
    feedback_suggestions_required_columns = [
        "exercise_id", "submission_id", "feedback_id", "feedback_text", "feedback_detail_text", "feedback_credits",
        "feedback_grading_instruction_id", "text_block_start_index", "text_block_end_index", "feedback_type"
    ]

    # Validate columns
    validate_columns(data, data_required_columns)
    validate_columns(feedback_suggestions, feedback_suggestions_required_columns)

    # Check for invalid IDs in feedback suggestions
    invalid_exercises = set(feedback_suggestions["exercise_id"]) - set(data["exercise_id"])
    invalid_submissions = set(feedback_suggestions["submission_id"]) - set(data["submission_id"])
    if invalid_exercises or invalid_submissions:
        raise ValueError(
            f"Invalid IDs in feedback suggestions:\n"
            f"Exercises: {invalid_exercises}\n"
            f"Submissions: {invalid_submissions}"
        )

    # Check for overlapping feedback
    overlap = pd.merge(
        data[["exercise_id", "submission_id", "feedback_id", "feedback_type"]],
        feedback_suggestions[["exercise_id", "submission_id", "feedback_id", "feedback_type"]],
        on=["exercise_id", "submission_id", "feedback_id", "feedback_type"],
        how="inner"
    )
    if not overlap.empty:
        raise ValueError(
            f"Overlapping feedback suggestions detected:\n"
            f"{overlap[['exercise_id', 'submission_id', 'feedback_id']].to_dict(orient='records')}"
        )

    # Merge feedback suggestions into the existing data to include exercise and submission info
    dropped_columns = list(set(feedback_suggestions_required_columns) - set(data_required_columns))
    enriched_feedback_suggestions = pd.merge(
        data.drop(columns=dropped_columns, errors="ignore"),
        feedback_suggestions,
        on=["exercise_id", "submission_id"],
        how="right"
    )

    # Concatenate enriched feedback suggestions with the original data
    combined_data = pd.concat([data, enriched_feedback_suggestions], ignore_index=True).drop_duplicates()

    # Calculate total submission counts per exercise
    total_submission_counts = data.groupby("exercise_id")["submission_id"].nunique().reset_index()
    total_submission_counts.rename(columns={"submission_id": "total_submission_count"}, inplace=True)

    # Calculate submission counts for each exercise and feedback type
    submission_counts_by_feedback_type = combined_data.groupby(["exercise_id", "feedback_type"])["submission_id"].nunique().reset_index()

    # Merge total submission counts with submission counts by feedback type
    feedback_comparison = pd.merge(
        submission_counts_by_feedback_type,
        total_submission_counts,
        on="exercise_id",
        how="left"
    )

    # Calculate missing feedback per exercise and feedback type
    feedback_comparison["missing_feedback"] = feedback_comparison["total_submission_count"] - feedback_comparison["submission_id"]

    # Print warnings for missing feedback
    for _, row in feedback_comparison.iterrows():
        if row["missing_feedback"] > 0:
            print(
                f"Warning: Exercise ID {int(row['exercise_id'])} (Feedback Type: {row['feedback_type']}): "
                f"{int(row['missing_feedback'])} submissions without feedback "
                f"({int(row['missing_feedback'])}/{int(row['total_submission_count'])})."
            )

    return combined_data


def fill_missing_feedback_with_tutor_feedback(data: pd.DataFrame) -> pd.DataFrame:
    """
    Fills missing feedback entries for submissions by copying Tutor feedback for the corresponding feedback type.
    Ensures all submissions have Tutor feedback before proceeding.

    Args:
        data (pd.DataFrame): The DataFrame containing all existing feedback, including Tutor feedback.

    Returns:
        pd.DataFrame: A DataFrame in the same format as the input, with missing feedback filled.

    Raises:
        ValueError: If any submission is missing Tutor feedback.
    """
    # Required columns
    required_columns = [
        "exercise_id", "submission_id", "feedback_type", "feedback_text", "feedback_detail_text",
        "feedback_credits", "feedback_grading_instruction_id", "text_block_start_index", "text_block_end_index"
    ]
    validate_columns(data, required_columns)

    # Ensure Tutor feedback exists in the data
    if "Tutor" not in data["feedback_type"].unique():
        raise ValueError("The input data must contain 'Tutor' feedback to fill missing entries.")

    # Verify that every submission has Tutor feedback
    submissions_with_tutor = data[data["feedback_type"] == "Tutor"]["submission_id"].unique()
    all_submissions = data["submission_id"].unique()
    missing_tutor_submissions = set(all_submissions) - set(submissions_with_tutor)

    if missing_tutor_submissions:
        raise ValueError(
            f"The following submissions are missing Tutor feedback: {missing_tutor_submissions}"
        )

    # Get unique feedback types (excluding Tutor)
    feedback_types = data["feedback_type"].unique()
    feedback_types = feedback_types[feedback_types != "Tutor"]

    # Filter Tutor feedback
    tutor_feedback = data[data["feedback_type"] == "Tutor"]

    # DataFrame to store newly filled feedback
    filled_feedback_entries = []

    # Iterate through all feedback types
    for feedback_type in feedback_types:
        # Identify submissions missing the current feedback type
        submissions_with_feedback = data[data["feedback_type"] == feedback_type]["submission_id"].unique()
        missing_submissions = tutor_feedback[~tutor_feedback["submission_id"].isin(submissions_with_feedback)]

        # Copy Tutor feedback for the missing submissions and adjust feedback type
        for _, tutor_row in missing_submissions.iterrows():
            filled_feedback_entries.append({
                "exercise_id": tutor_row["exercise_id"],
                "submission_id": tutor_row["submission_id"],
                "feedback_id": tutor_row["feedback_id"],  # Duplicate IDs within feedback_type groups are acceptable
                "feedback_type": feedback_type,
                "feedback_text": tutor_row["feedback_text"],
                "feedback_detail_text": tutor_row["feedback_detail_text"],
                "feedback_credits": tutor_row["feedback_credits"],
                "feedback_grading_instruction_id": tutor_row["feedback_grading_instruction_id"],
                "text_block_start_index": tutor_row["text_block_start_index"],
                "text_block_end_index": tutor_row["text_block_end_index"],
            })

    # Create a DataFrame from the newly filled feedback
    filled_feedback_df = pd.DataFrame(filled_feedback_entries)

    # Log the number of submissions added per exercise and feedback type
    if not filled_feedback_df.empty:
        counts = filled_feedback_df.groupby(["exercise_id", "feedback_type"])["submission_id"].nunique().reset_index(name="added_count")
        for _, row in counts.iterrows():
            print(
                f"Exercise ID {row['exercise_id']} (Feedback Type: {row['feedback_type']}): "
                f"{row['added_count']} submissions filled with Tutor feedback."
            )
    else:
        print("No missing feedback was filled.")

    complete_data = add_feedback_suggestions_to_data(data, filled_feedback_df)

    # Concatenate the original data and the newly filled feedback
    updated_data = pd.concat([data, complete_data], ignore_index=True)

    return updated_data
