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
sampled_exercises = pd.read_csv("../data/1_sampled_exercises.csv")

# Perform sampling
sampled_submissions = systematic_random_sampling(sampled_exercises, EXERCISE_SAMPLES, random_seed=42)
sampled_submissions.to_csv("../data/2_sampled_submissions.csv", index=False)

# sampled_submissions = pd.read_csv("../data/2_sampled_submissions.csv")

# %%
from evaluation.service.json_service import group_exercise_data, exercises_to_json

exercises = group_exercise_data(sampled_submissions, "Tutor")
exercises_to_json(exercises, "../data/2_exercise_jsons")
