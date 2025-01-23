# import os
# import json

# def load_indices(index_file):
#     """ Load the indices from the file or return an empty dictionary if the file does not exist. """
#     if os.path.exists(index_file):
#         with open(index_file, 'r', encoding="utf-8") as f:
#             return json.load(f)
#     else:
#         return {}

# def store_embedding_index(exercise_id, submission_id,feedback):
#     """ Store a new submission and exercise ID with an auto-incrementing index. """
#     index_file = f"indices_{exercise_id}.json"
#     indices = load_indices(index_file)
#     next_index = len(indices)
#     print(feedback)
#     indices[next_index] = {
#         "exercise_id": exercise_id,
#         "submission_id": submission_id,
#         "feedback": feedback.dict()
#     }

#     with open(index_file, 'w', encoding="utf-8") as f:
#         json.dump(indices, f, indent=4)

#     print(f"Stored new entry: Exercise ID {exercise_id}, Submission ID {submission_id} at index {next_index}")

# def retrieve_embedding_index(index,exercise_id):
#     index_file = f"indices_{exercise_id}.json"
#     index = str(index)
#     indices = load_indices(index_file)

#     if index in indices:
#         return indices[index]["exercise_id"], indices[index]["submission_id"]

#     return None, None

# def retrieve_feedback(index,exercise_id):
#     index_file = f"indices_{exercise_id}.json"
#     index = str(index)
#     indices = load_indices(index_file)

#     if index in indices:
#         return indices[index]["feedback"]

#     return None