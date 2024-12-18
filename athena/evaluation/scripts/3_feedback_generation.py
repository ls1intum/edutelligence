# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.4
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %%
import pandas as pd

sampled_submissions = pd.read_csv("../data/2_sampled_submissions.csv")

# %% [markdown]
# ### Upload the json files from data/2_exercise_jsons to the playground. In evaluation mode, generate feedback for each exercise and export the results. Make sure that the configuration names for feedback generation do not contain underscores '_'.
#
# The downloaded json files should have the following naming scheme:
#
# ```text_results_<Configuration name (e.g.: LLM)>_<...>```
#
# **Do not change the names of the downloaded files!**
#
# Save these files in the data/3_feedback_suggestions directory

# %%
from evaluation.service.json_service import read_result_files_to_dataframe, add_feedback_suggestions_to_data, fill_missing_feedback_with_tutor_feedback

feedback_suggestions = read_result_files_to_dataframe("../data/3_feedback_suggestions")

sampled_submissions_with_feedback = add_feedback_suggestions_to_data(sampled_submissions, feedback_suggestions)
sampled_submissions_with_feedback = fill_missing_feedback_with_tutor_feedback(sampled_submissions_with_feedback)

sampled_submissions_with_feedback = sampled_submissions_with_feedback.assign(feedback_text=None)

sampled_submissions_with_feedback.to_csv("../data/3_sampled_submissions_with_feedback.csv", index=False)

# %%
from evaluation.service.json_service import group_exercise_data, exercises_to_json

exercises = group_exercise_data(sampled_submissions_with_feedback)
exercises_to_json(exercises, "../data/3_submissions_with_categorized_feedback_jsons")

# %%
# Group by 'exercise_id' and 'result_score' to calculate submission counts
grouped_data = (
    sampled_submissions_with_feedback
    .groupby(["exercise_id", "result_score"])
    .agg(
        submission_count=("submission_id", "nunique")  # Count unique submissions per score
    )
    .reset_index()
)

# Calculate total submissions per exercise
total_submissions_per_exercise = (
    sampled_submissions_with_feedback
    .groupby("exercise_id")["submission_id"]
    .nunique()
    .reset_index()
    .rename(columns={"submission_id": "total_submission_count"})
)

# Merge total submissions into the grouped data
grouped_data = grouped_data.merge(total_submissions_per_exercise, on="exercise_id", how="left")

# Process feedback types
feedback_types = sampled_submissions_with_feedback["feedback_type"].unique()

for feedback_type in feedback_types:
    # Filter data for the current feedback type
    feedback_data = sampled_submissions_with_feedback[sampled_submissions_with_feedback["feedback_type"] == feedback_type]

    # Group by 'exercise_id' and 'result_score' to calculate feedback counts
    feedback_count = (
        feedback_data
        .groupby(["exercise_id", "result_score"])["feedback_id"]
        .nunique()
        .reset_index()
        .rename(columns={"feedback_id": f"feedback_count_{feedback_type}"})
    )
    grouped_data = grouped_data.merge(feedback_count, on=["exercise_id", "result_score"], how="left")
    grouped_data[f"feedback_count_{feedback_type}"] = grouped_data[f"feedback_count_{feedback_type}"].fillna(0).astype(int)
    
    # Group by 'exercise_id' to calculate total feedback counts
    total_feedback_count = (
        feedback_data
        .groupby("exercise_id")["feedback_id"]
        .nunique()
        .reset_index()
        .rename(columns={"feedback_id": f"total_feedback_count_{feedback_type}"})
    )
    grouped_data = grouped_data.merge(total_feedback_count, on="exercise_id", how="left")
    grouped_data[f"total_feedback_count_{feedback_type}"] = grouped_data[f"total_feedback_count_{feedback_type}"].fillna(0).astype(int)
    
    # Group by 'exercise_id' and 'result_score' to calculate average feedback counts
    grouped_data[f"average_feedback_count_{feedback_type}"] = (
        grouped_data[f"feedback_count_{feedback_type}"] / grouped_data["submission_count"]
    ).fillna(0)


# Display the final grouped data
grouped_data.to_csv("../data/2_feedback_counts.csv", index=False)
grouped_data
