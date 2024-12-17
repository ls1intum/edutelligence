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
import plotly.graph_objects as go

# Initialize lists to store the hierarchical data
labels = []
parents = []
values = []

# Root node
labels.append("All Exercises")
parents.append("")
values.append(0)  # Root node value

# Exercises
num_exercises = 4
submissions_per_exercise = 25
feedback_types = ["Tutor", "LLM", "CoFee"]
metrics = ["Completeness", "Correctness", "Actionability", "Tone"]

for ex in range(1, num_exercises + 1):
    exercise_label = f"Exercise {ex}"
    labels.append(exercise_label)
    parents.append("All Exercises")
    values.append(0)  # Exercise node value

    # Submissions (grouped as "25 submissions")
    submission_label = f"{exercise_label} - 25 Submissions"
    labels.append(submission_label)
    parents.append(exercise_label)
    values.append(0)  # Grouped submissions node value

    # Feedback Types
    for feedback in feedback_types:
        feedback_label = f"{submission_label} - {feedback} Feedback"
        labels.append(feedback_label)
        parents.append(submission_label)
        values.append(0)  # Feedback node value

        # Metrics
        for metric in metrics:
            metric_label = f"{feedback_label} - {metric}"
            labels.append(metric_label)
            parents.append(feedback_label)
            values.append(1)  # Metric node value

# Create the icicle chart
fig = go.Figure(go.Icicle(
    labels=labels,
    parents=parents,
    values=values,
    tiling=dict(orientation='v'),  # 'v' for vertical orientation (root at the top)
    marker=dict(colorscale='Blues')  # Modern color scale
))

# Update layout for better visualization
fig.update_layout(
    title='Hierarchical Structure of Exercises, Submissions, Feedback, and Metrics',
    margin=dict(t=50, l=25, r=25, b=25),
    template='plotly_white'  # Modern-looking template
)

# Display the figure
fig.show()
