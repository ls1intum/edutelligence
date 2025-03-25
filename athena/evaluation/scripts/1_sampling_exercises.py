# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.7
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# ## Get the data from the database
# Sample the exercise ids manually from the available exercises and adapt the `EXERCISE_IDS` variable accordingly.
# The `fetch_data_from_db` function fetches the data from the database for the specified exercise IDs.

# %%
from athena.evaluation.service.db_service import fetch_data_from_db
from langid import classify

EXERCISE_IDS = {4066, 642, 544, 506}
data = fetch_data_from_db(EXERCISE_IDS)

# %% [markdown]
# ## Data Preprocessing
# The data preprocessing steps include:
# - Dropping rows with missing or invalid data.
# - Filtering out non-English submissions.
#
# You can adapt the data preprocessing steps based on the requirements of your evaluation.

# %% [markdown]
# ### Drop Rows with Missing or Invalid Data
# Drops the rows with missing data in the `submission_text` and `result_score` columns. Also, filters out submissions with empty text.

# %%
# Drop rows with missing or invalid data
data = data.dropna(subset=["submission_text", "result_score"])
data = data[data["submission_text"].str.strip() != ""]

# %% [markdown]
# ### Filter Out Non-English Submissions
# Filters out non-English submissions using the `langid` library.

# %%
unique_texts = data["submission_text"].unique()
classification_results = {text: classify(text)[0] == "en" for text in unique_texts}

data["is_english"] = data["submission_text"].map(classification_results)
data = data[data["is_english"]]

data = data.drop(columns=["is_english"])

# %% [markdown]
# ## Save the Sampled Exercises in a CSV File
# Save the sampled exercises to a CSV file for the next steps in the evaluation process.
# You can also retrieve the sampled exercises from an existing CSV file.

# %%
data.to_csv("../data/1_sampled_exercises.csv", index=False)
# data = pd.read_csv("../data/1_sampled_exercises.csv")

# %% [markdown]
# ## Examples of Analysing the Sampled Exercises
# The following examples demonstrate some basic analysis of the sampled exercises.

# %%
overall_submissions = data["submission_id"].nunique()
print(f"Overall number of submissions: {overall_submissions}")

# %% [markdown]
# Creates a grouped DataFrame to count the number of distinct feedback IDs, submissions, and total feedbacks per score.
# Saves the data to a CSV file for further analysis.

# %%
grouped_data = (
    data
    .groupby(["exercise_id", "result_score"])
    .agg(
        distinct_feedback_count=("feedback_id", "nunique"),  # Count distinct feedback IDs per score
        submission_count=("submission_id", "nunique"),       # Count distinct submissions per score
        feedback_count=("feedback_id", "nunique")            # Total feedbacks per score
    )
    .reset_index()
)

total_feedbacks_per_exercise = (
    data
    .groupby("exercise_id")["feedback_id"]
    .nunique()
    .reset_index()
    .rename(columns={"feedback_id": "total_feedback_count"})
)

total_submissions_per_exercise = (
    data
    .groupby("exercise_id")["submission_id"]
    .nunique()
    .reset_index()
    .rename(columns={"submission_id": "total_submission_count"})
)

# Merge the total feedback count and total submission count back into the grouped data
grouped_data = grouped_data.merge(total_feedbacks_per_exercise, on="exercise_id")
grouped_data = grouped_data.merge(total_submissions_per_exercise, on="exercise_id")

# Calculate average number of feedbacks per exercise and score
grouped_data["avg_feedbacks_per_score"] = (
    grouped_data["feedback_count"] / grouped_data["submission_count"]
)

grouped_data = grouped_data[[
    "exercise_id",
    "result_score",
    "submission_count",
    "total_submission_count",
    "total_feedback_count",
    "feedback_count",
    "avg_feedbacks_per_score"
]]

grouped_data.to_csv("../data/grouped_data.csv", index=False)

# %% [markdown]
# Visualize the relationship between the scores and the average number of feedbacks per score using the grouped data from the previous step.

# %%
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Load the grouped data
grouped_data = pd.read_csv("../data/grouped_data.csv")

# Create a color and marker map for exercises
exercise_ids = grouped_data["exercise_id"].unique()
colors = plt.cm.tab10(range(len(exercise_ids)))  # Use a colormap for distinct colors
markers = ['o', 's', 'D', '^', 'v', 'P', '*', 'X']  # Different marker styles
marker_map = {exercise_id: markers[i % len(markers)] for i, exercise_id in enumerate(exercise_ids)}
color_map = {exercise_id: colors[i] for i, exercise_id in enumerate(exercise_ids)}

# Create the scatter plot
plt.figure(figsize=(10, 6))

for exercise_id in exercise_ids:
    subset = grouped_data[grouped_data["exercise_id"] == exercise_id]
    x = subset["avg_feedbacks_per_score"]
    y = subset["result_score"]

    # Scatter points
    plt.scatter(
        x, y,
        label=f"Exercise {exercise_id}",
        color=color_map[exercise_id],
        marker=marker_map[exercise_id],
        s=100,  # Marker size
        alpha=0.7  # Transparency
    )

    # Compute regression line
    if len(subset) > 1:  # Regression is meaningful only if there are multiple points
        coefficients = np.polyfit(x, y, 1)  # Linear regression (degree=1)
        regression_line = np.poly1d(coefficients)
        plt.plot(
            x, regression_line(x),
            color=color_map[exercise_id],
            linestyle='--',
            linewidth=2,
            alpha=0.7
        )

# Add labels and legend
plt.xlabel("Average Number of Feedbacks per Score", fontsize=12)
plt.ylabel("Scores", fontsize=12)
plt.title("Scores vs. Average Number of Feedbacks per Score", fontsize=14)
plt.legend(title="Exercises", loc="upper left", fontsize=10)
plt.grid(True)
plt.tight_layout()

# Show the plot
plt.show()
