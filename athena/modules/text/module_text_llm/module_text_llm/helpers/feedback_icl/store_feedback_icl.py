import numpy as np
import os
from athena.text import Submission, Exercise, Feedback
from typing import List
from athena.logger import logger
from module_text_llm.helpers.feedback_icl.generate_embeddings import embed_text
from module_text_llm.helpers.feedback_icl.store_indices_icl import store_embedding_index
from sklearn.metrics.pairwise import cosine_similarity

def store_feedback_icl(submission: Submission, exercise: Exercise, feedbacks: List[Feedback]):
    logger.info("Storing feedback for submission %d of exercise %d.", submission.id, exercise.id)
    for feedback in feedbacks:
        chunk = get_reference(feedback, submission.text)
        embedding = embed_text(chunk)
        save_embedding(embedding, exercise.id, submission.id, feedback)

def save_embedding(embedding, exercise_id):
    embeddings_file = f"embeddings_{exercise_id}.npy"

    try:
        # Check if the embeddings file already exists
        if os.path.exists(embeddings_file):
            # Load existing embeddings
            existing_embeddings = np.load(embeddings_file)
            # Append the new embedding
            updated_embeddings = np.vstack((existing_embeddings, embedding))
        else:
            # Create a new array for the embedding
            updated_embeddings = np.array([embedding], dtype=np.float32)

        # Save the updated embeddings back to the file
        np.save(embeddings_file, updated_embeddings)
    except Exception as e:
        logger.error(f"Error while saving embedding for exercise {exercise_id}: {e}")
    
    
def query_embedding(query_embedding, exercise_id, k=5):
    # Define the path to the embedding file
    embeddings_file = os.path.abspath(f"embeddings_{exercise_id}.npy")
    
    # Check if the embeddings file exists
    if not os.path.exists(embeddings_file):
        print(f"Error: The embeddings file '{embeddings_file}' does not exist.")
        return None
    
    try:
        # Load the embeddings from the file
        all_embeddings = np.load(embeddings_file)
    except Exception as e:
        print(f"Error while loading the embeddings file: {e}")
        return None

    try:
        # Ensure the query embedding has the correct shape
        query_embedding = np.array([query_embedding], dtype=np.float32)
        if query_embedding.ndim != 2 or query_embedding.shape[1] != all_embeddings.shape[1]:
            print("Error: Query embedding shape does not match the embeddings' dimensions.")
            return None
    except Exception as e:
        print(f"Error with query embedding format: {e}")
        return None

    try:
        # Compute cosine similarities
        similarities = cosine_similarity(query_embedding, all_embeddings).flatten()
        
        # Get the indices of the top-k most similar embeddings
        top_k_indices = np.argsort(similarities)[::-1][:k]

        return top_k_indices
    except Exception as e:
        print(f"Error during similarity computation: {e}")
        return None
    
def get_reference(feedback, submission_text):
    if (feedback.index_start is not None) and (feedback.index_end is not None):
        return submission_text[feedback.index_start:feedback.index_end ]
    return submission_text
    
def check_if_embedding_exists(exercise_id):
    return os.path.exists(f"embeddings_{exercise_id}.index")