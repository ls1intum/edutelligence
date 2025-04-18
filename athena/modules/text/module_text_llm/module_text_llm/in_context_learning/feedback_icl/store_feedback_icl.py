import numpy as np
import os
from athena.text import Submission, Exercise, Feedback
from typing import List
from athena.logger import logger
from module_text_llm.in_context_learning.feedback_icl.generate_embeddings import embed_text
import weaviate
import weaviate.classes as wvc
from weaviate.classes.query import Filter

def create_schema(client):
    """
    Creates a schema with the information needed for ICL.
    """
    feedback_collection = client.collections.create(
    name="Feedback",
    vectorizer_config=wvc.config.Configure.Vectorizer.none(),
    properties=[
        wvc.config.Property(name="exercise_id", data_type=wvc.config.DataType.NUMBER),
        wvc.config.Property(name="submission_id", data_type=wvc.config.DataType.NUMBER),
        wvc.config.Property(name="title", data_type=wvc.config.DataType.TEXT),
        wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
        wvc.config.Property(name="credits", data_type=wvc.config.DataType.NUMBER),
        wvc.config.Property(name="grading_id", data_type=wvc.config.DataType.NUMBER),
    ]
)
    
def store_feedback_icl(submission: Submission, exercise: Exercise, feedbacks: List[Feedback]):
    client = weaviate.connect_to_local()
    try:
        create_schema(client)
    finally:
        logger.info("Storing feedback for submission %d of exercise %d.", submission.id, exercise.id)
        for feedback in feedbacks:
            chunk = get_reference(feedback, submission.text)
            embedding = embed_text(chunk) 
            store_feedback(embedding, exercise.id, submission.id, feedback,chunk, client)
    client.close() 
    
def store_feedback(embedding, exercise_id, submission_id, feedback,chunk, client):
    """
    Store feedback in the Weaviate database. 
    """
    feedback_collection = client.collections.get("Feedback")
    uuid = feedback_collection.data.insert(
        properties={
            "exercise_id": exercise_id,
            "submission_id": submission_id,
            "title": feedback.title,
            "description": feedback.description,
            "credits": feedback.credits,
            "grading_id": feedback.structured_grading_instruction_id,
            "reference": chunk
        },
        vector=embedding, 
    )
    print(uuid)
    print("Feedback stored successfully.")
    return uuid

def query_embedding (query,exercise_id,results_limit=1):
    logger.info("Querying weaviate database")
    client = weaviate.connect_to_local()
    feedbacks = client.collections.get("Feedback")
    embedded_query = embed_text(query)

    results = feedbacks.query.near_vector(
        near_vector=embedded_query,
        limit = results_limit,
        filters=Filter.by_property("exercise_id").equal(exercise_id),
        return_metadata=wvc.query.MetadataQuery(certainty=True)
    )
    client.close()
    return results

def get_reference(feedback, submission_text):
    if (feedback.index_start is not None) and (feedback.index_end is not None):
        return submission_text[feedback.index_start:feedback.index_end ]
    return submission_text
