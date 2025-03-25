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

# %%
from io import StringIO

import pandas as pd

from athena.evaluation.service.json_service import group_exercise_data

# Load the data
data = pd.read_csv("../data/3_sampled_submissions_with_feedback.csv")
feedback_types = data["feedback_type"].unique()
print(f"Loaded data with feedback types: {feedback_types}")

number_of_exercises = data["exercise_id"].nunique()
print(f"Number of exercises: {number_of_exercises}")

number_of_submissions = data["submission_id"].nunique()
print(f"Number of submissions: {number_of_submissions}")

# %% [markdown]
# Define the metrics you want to use in the evaluation. You can also use the predefined metrics from the metrics file.

# %%

from athena.evaluation.prompts.metrics import completeness, correctness, actionability, tone

metrics = [completeness, correctness, actionability, tone]
print(f"Loaded metrics: {[metric.title for metric in metrics]}")

# %%

# %% [markdown]
# Test for a single submission + feedback type
# Look through the data for a suitable submission id. Then, select a feedback type to test the evaluation.

# %%
import os
from langchain_openai import AzureChatOpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

model_name = os.getenv("LLM_EVALUATION_MODEL")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
api_base = os.getenv("AZURE_OPENAI_ENDPOINT")
api_version = os.getenv("OPENAI_API_VERSION")

model = AzureChatOpenAI(
    deployment_name=model_name.replace("azure_openai_", ""),
    openai_api_key=api_key,
    azure_endpoint=api_base,
    openai_api_version=api_version,
    temperature=0,
)

# %%
from athena.evaluation.service.llm_service import get_logprobs_langchain
from athena.evaluation.prompts.llm_evaluation_prompt import get_formatted_prompt

submission_id = 2506896
feedback_type = "Tutor"

submission_data = data[data["submission_id"] == submission_id]
submission_data.head()

# %%
exercise_data = group_exercise_data(submission_data, feedback_type)

prompts = []
for exercise in exercise_data:
    print(f"Exercise ID: {exercise.id}")
    for submission in exercise.submissions:
        prompt = get_formatted_prompt(exercise, submission, submission.feedbacks, metrics)
        prompts.append(prompt)

        # Nicely print the prompt
        for message in prompt:
            print(f"--- {message.type.upper()} MESSAGE ---")
            print(message.content)
            print("\n")


assessment = get_logprobs_langchain(prompts[0], model)
print(assessment)
print(prompts[0])

# %%
assessment

# %%
import json

test = assessment.response.response_metadata.get("logprobs")

# Flatten the data
flat_data = []
token_index = 0
for entry in test['content']:
    # Basic token information
    base_entry = {
        'token_index': token_index,
        'token': entry['token'],
        'bytes': entry['bytes'],
        'logprob': entry['logprob']
    }

    # Flatten top_logprobs
    for top_logprob in entry['top_logprobs']:
        flattened_entry = base_entry.copy()  # Copy base entry
        flattened_entry.update({
            'top_logprob_token': top_logprob['token'],
            'top_logprob_bytes': top_logprob['bytes'],
            'top_logprob_logprob': top_logprob['logprob']
        })
        flat_data.append(flattened_entry)

    token_index += 1

# Convert to DataFrame
df = pd.DataFrame(flat_data)
df
