import numpy as np
import os
from athena.text import Submission, Exercise, Feedback
from typing import List
from athena.logger import logger
from module_text_llm.in_context_learning.feedback_icl.generate_embeddings import embed_text
import weaviate
import weaviate.classes as wvc


def create_schema(client):
    """
    Create a schema with two classes: Question and Answer.
    Each class has properties for storing relevant information.
    """
    
    # Define the Question class
    questions = client.collections.create(
        name="Feedback",
        vectorizer_config=wvc.config.Configure.Vectorizer.none(),
        properties=[
            wvc.config.Property(name="exercise_id", data_type=wvc.config.DataType.NUMBER),
            wvc.config.Property(name="submission_id", data_type=wvc.config.DataType.NUMBER),
            wvc.config.Property(name="title", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="description", data_type=wvc.config.DataType.TEXT),
            wvc.config.Property(name="credits", data_type=wvc.config.DataType.NUMBER),
            wvc.config.Property(name="grading_id", data_type=wvc.config.DataType.UUID),
        ]
    )

    print("Schema ICL created.")
    print(questions.config.get(simple=False))
    
def store_feedback_icl(submission: Submission, exercise: Exercise, feedbacks: List[Feedback]):
    client = weaviate.connect_to_local()
    try:
        create_schema(client)
    finally:
        logger.info("Storing feedback for submission %d of exercise %d.", submission.id, exercise.id)
        
        for feedback in feedbacks:
            print("doing feedback")
            chunk = get_reference(feedback, submission.text)
            embedding = embed_text(chunk) 
            store_feedback(embedding, exercise.id, submission.id, feedback, client)
            # save_embedding(embedding, exercise.id)
            # store_embedding_index(exercise.id, submission.id, feedback)
    client.close() 
def store_feedback(embedding, exercise_id, submission_id, feedback, client):
    """
    Store feedback in the Weaviate database. 
    """
    print("storing feedback")
    questions = client.collections.get("Feedback")
    uuid = questions.data.insert(
        properties={
            "exercise_id": exercise_id,
            "submission_id": submission_id,
            "title": feedback.title,
            "description": feedback.description,
            "credits": feedback.credits,
            "grading_id": feedback.structured_grading_instruction_id
        },
        vector=embedding, 
    )
    print(uuid)
    print("Feedback stored successfully.")
    return uuid


# Here is the usage of the function:
#    list_of_indices = query_embedding(query_submission,exercise_id)
#TODO implement a filter for the exercise id. Use the certainity limit to filter the results.
def query_embedding (query,exercise_id,results_limit=1, threshold=0.5):
    logger.info("Querying")
    client = weaviate.connect_to_local()
    feedbacks = client.collections.get("Feedback")
    embedded_query = embed_text(query)
    # print("embedded query",embedded_query)

    results = feedbacks.query.near_vector(
        near_vector=embedded_query,
        limit = results_limit,
        return_metadata=wvc.query.MetadataQuery(certainty=True)
    )
    
    print(results)
    client.close()
    return results
    # return "test"
    
def get_reference(feedback, submission_text):
    if (feedback.index_start is not None) and (feedback.index_end is not None):
        return submission_text[feedback.index_start:feedback.index_end ]
    return submission_text

def check_if_embedding_exists(exercise_id):
    """
    Check if the embedding index file exists for the given exercise ID.
    """
    return True