import json
import os

INDEX_FILE = "indices.json"

def load_indices():
    """ Load the indices from the file or return an empty dictionary if the file does not exist. """
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r') as f:
            return json.load(f)
    else:
        return {}

def store_embedding_index(exercise_id, submission_id):
    """ Store a new submission and exercise ID with an auto-incrementing index. """
    indices = load_indices()  # Load existing indices from the file
    next_index = len(indices)  # Calculate the next available index

    # Add the new entry to the dictionary with next_index as the key
    indices[next_index] = {
        "exercise_id": exercise_id,
        "submission_id": submission_id
    }

    # Write the updated dictionary back to the file
    with open(INDEX_FILE, 'w') as f:
        json.dump(indices, f, indent=4)

    print(f"Stored new entry: Exercise ID {exercise_id}, Submission ID {submission_id} at index {next_index}")

def retrieve_embedding_index(index):
    index = str(index)  # Convert index to string for dictionary lookup
    """ Retrieve the exercise_id and submission_id by index. """
    indices = load_indices()

    # Find the entry by index (direct dictionary lookup)
    if index in indices:
        return indices[index]["exercise_id"], indices[index]["submission_id"]

    return None, None  # Return None if index is not found