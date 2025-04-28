import pandas as pd
import numpy as np


def systematic_random_sampling(
    data: pd.DataFrame, exercise_samples: dict, random_seed: int = 42
) -> pd.DataFrame:
    """
    Performs systematic random sampling while preserving the original data format.

    Args:
        data (pd.DataFrame): The DataFrame containing all submission data.
        exercise_samples (dict): A dictionary mapping exercise IDs to the required number of samples.
        random_seed (int): Seed for random number generator for deterministic behavior.

    Returns:
        pd.DataFrame: A DataFrame containing the sampled submissions.
    """
    np.random.seed(random_seed)
    sampled_data = []

    for exercise_id, sample_size in exercise_samples.items():
        exercise_group = data[data["exercise_id"] == exercise_id]
        if exercise_group.empty:
            print(f"Warning: No data found for Exercise ID {exercise_id}.")
            continue

        grouped_submissions = exercise_group.groupby("submission_id")
        sorted_groups = grouped_submissions.first().sort_values(
            by=["result_score", "submission_id"], ascending=[False, True]
        )

        total_submissions = len(sorted_groups)

        if total_submissions == 0:
            print(f"Warning: No valid submissions for Exercise ID {exercise_id}.")
            continue

        if total_submissions <= sample_size:
            print(
                f"Warning: Taking all {total_submissions} submissions for Exercise ID {exercise_id}."
            )
            sampled_data.append(exercise_group)
            continue

        # Systematic sampling
        interval = total_submissions // sample_size
        start_index = np.random.randint(0, interval)

        # Determine sampled submission IDs
        sampled_submission_ids = sorted_groups.iloc[start_index::interval].index[
            :sample_size
        ]

        # Filter the original data for the sampled submission IDs
        sampled_group = exercise_group[
            exercise_group["submission_id"].isin(sampled_submission_ids)
        ]
        sampled_data.append(sampled_group)

    if sampled_data:
        sampled_data = pd.concat(sampled_data, ignore_index=True)
        submission_counts = sampled_data.groupby("exercise_id")[
            "submission_id"
        ].nunique()
        print(
            f"Sampled {submission_counts.sum()} submissions from {len(submission_counts)} exercises."
        )
        return sampled_data
    else:
        print("Error: No data was sampled.")
        return pd.DataFrame()
