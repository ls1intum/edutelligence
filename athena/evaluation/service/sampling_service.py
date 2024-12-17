import pandas as pd
import numpy as np


def systematic_random_sampling(data: pd.DataFrame, exercise_samples: dict, random_seed: int = 42) -> pd.DataFrame:
    """
    Performs systematic random sampling while preserving the original data format.

    Args:
        data (pd.DataFrame): The DataFrame containing all submission data.
        exercise_samples (dict): A dictionary mapping exercise IDs to the required number of samples.
        random_seed (int): Seed for random number generator for deterministic behavior.

    Returns:
        pd.DataFrame: A DataFrame containing the sampled submissions.
    """
    np.random.seed(random_seed)  # Set the random seed for reproducibility
    sampled_data = []

    for exercise_id, sample_size in exercise_samples.items():
        # Filter data for the current exercise
        exercise_group = data[data["exercise_id"] == exercise_id]

        if exercise_group.empty:
            print(f"Warning: No data found for Exercise ID {exercise_id}.")
            continue

        # Group submissions by 'submission_id' to handle duplicates
        grouped_submissions = exercise_group.groupby("submission_id")

        # Sort groups by score (descending) and submission_id (ascending)
        sorted_groups = (
            grouped_submissions.first()  # Use the first occurrence of each submission for sorting
            .sort_values(by=["result_score", "submission_id"], ascending=[False, True])
        )

        total_submissions = len(sorted_groups)

        if total_submissions == 0:
            print(f"Warning: No valid submissions for Exercise ID {exercise_id}.")
            continue

        if total_submissions <= sample_size:
            # If there are fewer submissions than the sample size, take all
            print(f"Warning: Taking all {total_submissions} submissions for Exercise ID {exercise_id}.")
            sampled_data.append(exercise_group)
            continue

        # Systematic sampling
        interval = total_submissions // sample_size
        start_index = np.random.randint(0, interval)  # Random start index within [0, interval-1]

        # Determine sampled submission IDs
        sampled_submission_ids = sorted_groups.iloc[start_index::interval].index[:sample_size]

        # Filter the original data for the sampled submission IDs
        sampled_group = exercise_group[exercise_group["submission_id"].isin(sampled_submission_ids)]
        sampled_data.append(sampled_group)

    # Combine all sampled data into a single DataFrame
    if sampled_data:
        sampled_data = pd.concat(sampled_data, ignore_index=True)

        # Print the counts
        print("Number of submissions per exercise:")
        submission_counts = sampled_data.groupby("exercise_id")["submission_id"].nunique()
        for exercise_id, count in submission_counts.items():
            print(f"Exercise ID {exercise_id}: {count} submissions")
        print(f"Total number of submissions: {submission_counts.sum()}")

        return sampled_data
    else:
        print("Error: No data was sampled.")
        return pd.DataFrame()