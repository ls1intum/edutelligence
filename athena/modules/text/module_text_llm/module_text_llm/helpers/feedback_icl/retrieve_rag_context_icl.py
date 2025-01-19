from athena.logger import logger
from module_text_llm.helpers.feedback_icl.store_indices_icl import retrieve_embedding_index, retrieve_feedback
from module_text_llm.helpers.feedback_icl.store_feedback_icl import query_embedding
from module_text_llm.helpers.feedback_icl.generate_embeddings import embed_text,embed_bert

def retrieve_rag_context_icl(submission_segment: str ,exercise_id: int) -> str:
    """
    This method takes a segment from a submission and for a given exercise id, 
    returns feedback that has been given for similar texts.

    Args:
        submission_segment: A segment of the submission.
        exercise_id: The id of the exercise.

    Returns:
        str: A formatted string of feedbacks which reference text similar to the submission_segment.
    """
    query_submission= embed_bert(submission_segment)

    rag_context = []
    
    list_of_indices = query_embedding(query_submission,exercise_id)
    if list_of_indices is not None:
        for index in list_of_indices[0]:
            if index != -1:
                stored_feedback = retrieve_feedback(index,exercise_id)

                rag_context.append({"submission_chunk": submission_segment, "feedback": stored_feedback})
        formatted_rag_context = format_rag_context(rag_context)
    else:
        formatted_rag_context = "There are no submission at the moment"
    return formatted_rag_context

def format_rag_context(rag_context):
    formatted_string = ""
    
    for context_item in rag_context:
        submission_text = context_item["submission_chunk"]
        feedback = context_item["feedback"]
        formatted_string += "**Tutor provided Feedback from previous submissions of this same exercise:**\n"
        feedback["text_reference"] = get_reference(feedback, submission_text)
        clean_feedback = {key: value for key, value in feedback.items() if key not in ["id","index_start","index_end","is_graded","meta"]} 

        formatted_string += f"{clean_feedback}\n"
        formatted_string += "\n" + "-"*40 + "\n"
    
    return formatted_string

def get_reference(feedback, submission_text):
    if (feedback["index_start"] is not None) and (feedback["index_end"] is not None):
        return submission_text[feedback["index_start"]:feedback["index_end"]]
    return submission_text
