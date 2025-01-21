from athena.logger import logger
from module_text_llm.index_storage import retrieve_embedding_index, retrieve_feedbacks
from module_text_llm.storage_embeddings import query_embedding
from module_text_llm.helpers.feedback_icl.generate_embeddings import embed_text,embed_text

def retrieve_rag_context(submission,exercise_id):
    query_submission= embed_text(submission.text)

    rag_context = []
    
    list_of_indices = query_embedding(query_submission,exercise_id)
    if list_of_indices is not None:
        for index in list_of_indices[0]:
            if index != -1:
                exercise_id, submission_id = retrieve_embedding_index(list_of_indices)
                stored_feedback = retrieve_feedbacks(index)
                if stored_feedback is not None:
                    for feedback_item in stored_feedback:
                        logger.info("- %s", feedback_item) 

                rag_context.append({"submission": submission.text, "feedback": stored_feedback})
        
        formatted_rag_context = format_rag_context(rag_context)
    else:
        formatted_rag_context = "There are no submission at the moment"
    return formatted_rag_context

def format_rag_context(rag_context):
    formatted_string = ""
    for context_item in rag_context:
        submission_text = context_item["submission"]
        feedback_list = context_item["feedback"]
        formatted_string += "**Tutor provided Feedback from previous submissions of this same exercise:**\n"
        for idx, feedback in enumerate(feedback_list, start=1):
            feedback["text_reference"] = get_reference(feedback, submission_text)
            clean_feedback = {key: value for key, value in feedback.items() if key not in ["id","index_start","index_end","is_graded","meta"]} 

            formatted_string += f"{idx}. {clean_feedback}\n"
        formatted_string += "\n" + "-"*40 + "\n"
    return formatted_string

def get_reference(feedback, submission_text):
    if (feedback["index_start"] is not None) and (feedback["index_end"] is not None):
        return submission_text[feedback["index_start"]:feedback["index_end"]]
    return submission_text
