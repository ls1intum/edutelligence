import numpy as np
import os
from athena.text import Submission, Exercise, Feedback
from typing import List
from athena.logger import logger
from module_text_llm.helpers.feedback_icl.generate_embeddings import embed_text
# from module_text_llm.helpers.feedback_icl.store_indices_icl import store_embedding_index
from sklearn.metrics.pairwise import cosine_similarity

def store_feedback_icl(submission: Submission, exercise: Exercise, feedbacks: List[Feedback]):
    logger.info("Storing feedback for submission %d of exercise %d.", submission.id, exercise.id)
    for feedback in feedbacks:
        if(feedback.structured_grading_instruction_id is not None):
            logger.info("Storing 1 ")
            is_good_reference, chunk = get_reference(feedback, submission.text)
            if is_good_reference:
                logger.info(chunk)
                embedding = embed_text(chunk)
                logger.info(embedding)
                save_embedding_with_metadata(embedding,submission, exercise.id, feedback.dict(),chunk)
            else: 
                logger.info("No good reference, not storing")
        else:
            logger.info("No instruction id, not storing")
        # save_embeddings_to_file([embedding], f"embeddings_{exercise.id}.npy")
        # save_embeddings_to_file(embedding, exercise.id, submission.id, feedback)

def save_embedding_with_metadata(embedding,submission, exercise_id, metadata,chunk):
    embeddings_file = f"embeddings_{exercise_id}.npy"

    # if metadata["index_start"] is not None and metadata["index_end"] is not None:
    #     reference = submission.text[metadata["index_start"]:metadata["index_end"]]
    #     print(reference)
    metadata["text_reference"] = chunk

    try:
        if os.path.exists(embeddings_file):
            existing_data = np.load(embeddings_file, allow_pickle=True).item()
            existing_data['embeddings'] = np.vstack((existing_data['embeddings'], embedding))
            existing_data['metadata'].append(metadata)
            # lets extend this with criteria, and only get for that criteria. for divide and conquer
        else:
            existing_data = {
                'embeddings': np.array([embedding], dtype=np.float32),
                'metadata': [metadata]
            }
        
        # Save the updated data
        np.save(embeddings_file, existing_data)
    except Exception as e:
        print(f"Error while saving embedding with metadata: {e}")

def load_embeddings_with_metadata(exercise_id):
    embeddings_file = f"embeddings_{exercise_id}.npy"
    if os.path.exists(embeddings_file):
        data = np.load(embeddings_file, allow_pickle=True).item()
        return data['embeddings'], data['metadata']
    else:
        print(f"Error: File '{embeddings_file}' does not exist.")
        return None, None
    
def save_embeddings_to_file(embeddings, filename="keyword_embeddings.npy"):
    """
    Save embeddings to a .npy file.
    Parameters:
        embeddings (np.ndarray): The embeddings to save.
        filename (str): The filename where embeddings will be saved.
    """
    np.save(filename, embeddings)
    print(f"Embeddings saved to {filename}")
    
    
def query_embedding(query_embedding, exercise_id, k=1):
    """
    Query the top-k most similar embeddings to the provided query_embedding
    for a given exercise ID. Return the corresponding metadata for these embeddings.

    Parameters:
    - query_embedding: A NumPy array representing the query embedding.
    - exercise_id: The ID of the exercise (used to locate the embeddings file).
    - k: The number of top similar embeddings to retrieve.

    Returns:
    - A list of metadata corresponding to the top-k most similar embeddings.
    """
    embeddings_file = f"embeddings_{exercise_id}.npy"
    
    # Check if the embeddings file exists
    if not os.path.exists(embeddings_file):
        logger.error(f"The embeddings file '{embeddings_file}' does not exist.")
        return None

    try:
        # Load the data (embeddings and metadata)
        data = np.load(embeddings_file, allow_pickle=True).item()
        # Here we would need to filter.
        all_embeddings = data['embeddings']
        all_metadata = data['metadata']
    except Exception as e:
        logger.error(f"Error while loading the embeddings file: {e}")
        return None

    try:
        # Ensure the query embedding has the correct shape
        query_embedding = np.array([query_embedding], dtype=np.float32)
        if query_embedding.ndim != 2 or query_embedding.shape[1] != all_embeddings.shape[1]:
            logger.error("Query embedding shape does not match the embeddings' dimensions.")
            return None
    except Exception as e:
        logger.error(f"Error with query embedding format: {e}")
        return None

    try:
        # Compute cosine similarities
        similarities = cosine_similarity(query_embedding, all_embeddings).flatten()
        
        # Get the indices of the top-k most similar embeddings
        top_k_indices = np.argsort(similarities)[::-1][:k]
        
        # Retrieve the metadata corresponding to the top-k indices
        top_k_metadata = [all_metadata[i] for i in top_k_indices]
        print(top_k_metadata)
        return top_k_metadata
    except Exception as e:
        logger.error(f"Error during similarity computation: {e}")
        return None
    
def get_reference(feedback, submission_text):
    if (feedback.index_start is not None) and (feedback.index_end is not None):
        if(feedback.index_end - feedback.index_start > 100):
            return True, submission_text[feedback.index_start:feedback.index_end]
    return False, None
    
def check_if_embedding_exists(exercise_id):
    return os.path.exists(f"embeddings_{exercise_id}.npy")