import faiss
import numpy as np
import os
from athena.text import Submission, Exercise, Feedback
from typing import List
from athena.logger import logger
from module_text_llm.helpers.feedback_icl.generate_embeddings import embed_bert
from module_text_llm.helpers.feedback_icl.store_indices_icl import store_embedding_index

def store_feedback_icl(submission: Submission, exercise: Exercise, feedbacks: List[Feedback]):
    logger.info("Storing feedback for submission %d of exercise %d.", submission.id, exercise.id)
    for feedback in feedbacks:
        chunk = get_reference(feedback, submission.text)
        embedding = embed_bert(chunk) 
        save_embedding(embedding, exercise.id)
        store_embedding_index(exercise.id, submission.id, feedback)
        
def save_embedding(embedding, exercise_id):
    if os.path.exists(f"embeddings_{exercise_id}.index"):
        index = faiss.read_index(f"embeddings_{exercise_id}.index")
    else:
        index = faiss.IndexFlatL2(embedding.shape[0])

    index.add(np.array([embedding], dtype=np.float32))
    faiss.write_index(index, f"embeddings_{exercise_id}.index")
    
def query_embedding(query_embedding,exercise_id, k=2):
    index_file = os.path.abspath(f"embeddings_{exercise_id}.index")

    
    if not os.path.exists(index_file):
        print(f"Error: The index file '{index_file}' does not exist.")
        return None
    
    try:
        index = faiss.read_index(index_file)
    except Exception as e:
        print(f"Error while reading the FAISS index: {e}")
        return None

    try:
        query_embedding = np.array([query_embedding], dtype=np.float32) 
        if query_embedding.ndim != 2 or query_embedding.shape[1] != index.d:
            print("Error: Query embedding shape does not match the index dimensions.")
            return None
    except Exception as e:
        print(f"Error with embedding format: {e}")
        return None
    
    try:
        # Search the index for nearest neighbors
        distances, indices = index.search(query_embedding, k)

        return indices
    except Exception as e:
        return None
    
def get_reference(feedback, submission_text):
    if (feedback.index_start is not None) and (feedback.index_end is not None):
        return submission_text[feedback.index_start:feedback.index_end ]
    return submission_text
    
def check_if_embedding_exists(exercise_id):
    return os.path.exists(f"embeddings_{exercise_id}.index")