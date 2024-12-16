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
from evaluation.service.sampling_service import systematic_random_sampling
import pandas as pd

EXERCISE_SAMPLES = {4066: 25, 642: 25, 544: 25, 506: 25}

# Load the data
data = pd.read_csv("../data/1_exercises.csv")

# # Perform sampling
# sampled_data = systematic_random_sampling(data, EXERCISE_SAMPLES, random_seed=42)

# TODO: Remove fixed sample and use the above code
SUBMISSION_IDS = [ 139272,  139116,  139092,  137979,  146986,  139974,  146499,
        146161,  143640,  147166,  145781,  144740,  145432,  145507,
        145692,  146363,  147065,  147077,  148060,  147628,  147671,
        147928,  148099,  148100,  148191,  148385,  193090,  198056,
        195020,  195158,  195074,  195732,  213075,  196262,  215308,
        197615,  197786,  209007,  208009,  205401,  207081,  214879,
        215473,  216261,  213445,  216732,  214827,  215683,  217153,
        216204,  216952,  217201,  217214,  277714,  277760,  277763,
        277769,  277796,  277811,  277833,  277882,  277895,  277908,
        277920,  277935,  277958,  278009,  278096,  278104,  278110,
        278122,  278139,  278217,  278256,  278329,  278333,  278387,
        278388,  278402,  283382, 2506878, 2506881, 2506952, 2507001,
       2507016, 2507128, 2507243, 2507260, 2507375, 2507502, 2507540,
       2507580, 2507585, 2507638, 2507664, 2507667, 2507717, 2507719,
       2507888, 2509555, 2510407, 2510862, 2511319, 2511404, 2511714]

sampled_data = data[data["submission_id"].isin(SUBMISSION_IDS)]

# Print the counts
print("Number of submissions per exercise:")
submission_counts = sampled_data.groupby("exercise_id")["submission_id"].nunique()
for exercise_id, count in submission_counts.items():
    print(f"Exercise ID {exercise_id}: {count} submissions")
print(f"Total number of submissions: {submission_counts.sum()}")

# %%
from evaluation.service.json_service import group_exercise_data, exercises_to_json

exercises = group_exercise_data(sampled_data)
exercises_to_json(exercises, "../data/2_exercise_jsons")

# %% [markdown]
# ### Upload the json exercises to the playground. In evaluation mode, generate feedback for each exercise and export the results.
# The downloaded json files should have the following naming scheme:
# text_results_<Configuration name (e.g.: LLM)>_<...>
#
# Make sure that the configuration names do not contain underscores '_'.
#
# Save these files in the data/2_results directory

# %%
from evaluation.service.json_service import read_result_files_to_dataframe, add_feedback_suggestions_to_data

feedback_suggestions = read_result_files_to_dataframe("../data/2_results_input")
data_with_feedback_suggestions = add_feedback_suggestions_to_data(sampled_data, feedback_suggestions)

# %%
from evaluation.service.json_service import fill_missing_feedback

complete_data = fill_missing_feedback(data_with_feedback_suggestions)
complete_data.to_csv("../data/2_exercises_with_feedback.csv", index=False)

# %%
# Group by 'exercise_id' and 'result_score' to calculate submission counts
grouped_data = (
    complete_data
    .groupby(["exercise_id", "result_score"])
    .agg(
        submission_count=("submission_id", "nunique")  # Count unique submissions per score
    )
    .reset_index()
)

# Calculate total submissions per exercise
total_submissions_per_exercise = (
    complete_data
    .groupby("exercise_id")["submission_id"]
    .nunique()
    .reset_index()
    .rename(columns={"submission_id": "total_submission_count"})
)

# Merge total submissions into the grouped data
grouped_data = grouped_data.merge(total_submissions_per_exercise, on="exercise_id", how="left")

# Process feedback types
feedback_types = complete_data["feedback_type"].unique()

for feedback_type in feedback_types:
    # Filter data for the current feedback type
    feedback_data = complete_data[complete_data["feedback_type"] == feedback_type]

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
