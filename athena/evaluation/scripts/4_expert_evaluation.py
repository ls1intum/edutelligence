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
# ## Expert Evaluation
# Conduct the expert evaluation by importing the json files from `data/3_submissions_with_categorized_feedback_jsons` into a new expert evaluation in the playground. Download the results as well as the evaluation configuration.
# Save the downloaded files in the `data/4_expert_evaluation` directory.

# %%
import os
import re
import json
import pandas as pd

def extract_selected_values(data, expert_id):
    """Extracts nested selected_values data into a flat structure."""
    rows = []

    selected_values = data.get("selected_values", {})
    for exercise_id, submissions in selected_values.items():
        for submission_id, metrics in submissions.items():
            for feedback_type_pseudo, score_dict in metrics.items():
                for metric_id, value in score_dict.items():
                    rows.append({
                        "expert_id": expert_id,
                        "exercise_id": exercise_id,
                        "submission_id": submission_id,
                        "metric_id": metric_id,
                        "feedback_type_pseudo": feedback_type_pseudo,
                        "value": value,
                        "has_started_evaluating": data.get("has_started_evaluating"),
                        "is_finished_evaluating": data.get("is_finished_evaluating"),
                        "current_submission_index": data.get("current_submission_index"),
                        "current_exercise_index": data.get("current_exercise_index")
                    })
    return rows

data_rows = []
data_dir = "../data/4_expert_evaluation"

for file in os.listdir(data_dir):
    if file.endswith(".json") and file.startswith("evaluation_progress"):
        with open(os.path.join(data_dir, file), "r") as f:
            expert_id = re.split(r"_|\.", file)[2]  # Extract numeric key
            json_data = json.load(f)
            data_rows.extend(extract_selected_values(json_data, expert_id))

data = pd.DataFrame(data_rows)

# %%
data

# %%
import os
import json
import pandas as pd

def extract_metrics_and_mappings(data, evaluation_id):
    """Extracts metrics and mappings from the evaluation config."""
    metrics_rows = []
    mappings_rows = []

    # Extract metrics
    for metric in data.get("metrics", []):
        metrics_rows.append({
            "metric_id": metric.get("id"),
            "title": metric.get("title"),
            "summary": metric.get("summary"),
            "description": metric.get("description")
        })

    # Extract mappings
    for feedback_type_pseudo, feedback_type in data.get("mappings", {}).items():
        mappings_rows.append({
            "feedback_type_pseudo": feedback_type_pseudo,
            "feedback_type": feedback_type
        })

    return metrics_rows, mappings_rows

# Process JSON files
metrics_rows = []
mappings_rows = []
data_dir = "../data/4_expert_evaluation"
evaluation_config_files = [file for file in os.listdir(data_dir) if file.endswith(".json") and file.startswith("evaluation_config")]

# Check if there is exactly one evaluation_config file
if len(evaluation_config_files) != 1:
    raise ValueError(f"Expected exactly one 'evaluation_config' file, but found {len(evaluation_config_files)}.")

# Process the single evaluation_config file
evaluation_config_file = evaluation_config_files[0]
with open(os.path.join(data_dir, evaluation_config_file), "r") as f:
    json_data = json.load(f)
    metrics, mappings = extract_metrics_and_mappings(json_data, expert_id)
    metrics_rows.extend(metrics)
    mappings_rows.extend(mappings)

# Convert lists to DataFrames
metrics = pd.DataFrame(metrics_rows)
mappings = pd.DataFrame(mappings_rows)

# %%
metrics

# %%
mappings

# %%
# Join mappings, metrics, and data
data = data.merge(mappings, on="feedback_type_pseudo")
data = data.merge(metrics, on="metric_id")

# %%
data
