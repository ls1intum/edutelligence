import json
import os
INDEX_FILE = "indices.json"

def load_indices():
    """ Load the indices from the file or return an empty dictionary if the file does not exist. """
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, 'r', encoding="utf-8") as f:
            return json.load(f)
    else:
        return {}
    
def store_embedding_index(exercise_id, submission_id,feedbacks):
    """ Store a new submission and exercise ID with an auto-incrementing index. """
    indices = load_indices()
    next_index = len(indices)
    indices[next_index] = {
        "exercise_id": exercise_id,
        "submission_id": submission_id,
        "feedbacks": [feedback.dict() for feedback in feedbacks]
    }

    with open(INDEX_FILE, 'w', encoding="utf-8") as f:
        json.dump(indices, f, indent=4)

    print(f"Stored new entry: Exercise ID {exercise_id}, Submission ID {submission_id} at index {next_index}")

def retrieve_embedding_index(index):
    index = str(index)
    indices = load_indices()

    if index in indices:
        return indices[index]["exercise_id"], indices[index]["submission_id"]

    return None, None

def retrieve_feedbacks(index):
    index = str(index)
    indices = load_indices()

    if index in indices:
        return indices[index]["feedbacks"]

    return None