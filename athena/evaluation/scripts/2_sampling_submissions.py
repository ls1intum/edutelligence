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
# ## Sampling Submissions
#
# Please adapt the `EXERCISE_SAMPLES` dictionary to specify the number of samples for each exercise. The dictionary maps `EXERCISE_IDS` (see 1_sampling_exercises) to the `number of samples`.
#

# %%
EXERCISE_SAMPLES = {4066: 25, 642: 25, 544: 25, 506: 25}

# %% [markdown]
# ### Systematic Random Sampling
# The goal is to obtain a representative sample of submissions for each exercise.
# The script uses systematic random sampling to achieve this. In systematic random sampling, we sort the submissions by score and then select submissions at regular intervals. The interval is calculated based on the total number of submissions and the required sample size.

# %%
from athena.evaluation.service.sampling_service import systematic_random_sampling
import pandas as pd

# Load the data
sampled_exercises = pd.read_csv("../data/1_sampled_exercises.csv")

# Perform sampling
sampled_submissions = systematic_random_sampling(sampled_exercises, EXERCISE_SAMPLES, random_seed=42)

# %% [markdown]
# ### Save the Sampled Submissions
# Save the sampled submissions to a CSV and JSON file for the next steps in the evaluation process.
# You can also retrieve the sampled submissions from an existing CSV file.

# %%
from athena.evaluation.service.json_service import group_exercise_data, exercises_to_json

sampled_submissions.to_csv("../data/2_sampled_submissions.csv", index=False)
# sampled_submissions = pd.read_csv("../data/2_sampled_submissions.csv")

exercises = group_exercise_data(sampled_submissions, "Tutor")
exercises_to_json(exercises, "../data/2_exercise_jsons")
