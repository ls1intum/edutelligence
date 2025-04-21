from module_text_llm.in_context_learning.feedback_icl.store_feedback_icl import query_embedding

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

    rag_context = []
    
    result_objects = query_embedding(submission_segment,exercise_id)
    for result in result_objects.objects:
        title = result.properties.get("title")
        description = result.properties.get("description")
        credits = result.properties.get("credits")
        reference = result.properties.get("reference")
        rag_context.append(format_context(title,description,credits,reference))
    return format_rag_context(rag_context) 

def format_context(title,description,credits,reference):
    formatted_string = ""
    formatted_string += f"""
    For the reference text in the submission: {reference}**\n
    The tutor provided the following feedback:\n
    **Title**: {title}\n
    **Description**: {description}\n
    **Credits**: {credits}\n
    **Reference text**: {reference}**\n
    **\n"""
    return formatted_string

def format_rag_context(rag_context):
    formatted_string = """  **Tutor provided Feedback from previous submissions of this same exercise.
    This are possible examples that could help with the grading of the current submission. However they are not identical
    so please be careful when using them. You must carefully decide whether this references are relevant.**\n
    **\n"""
    formatted_string += "\n" + "-"*40 + "\n"

    for context_item in rag_context:
        formatted_string += f"{context_item}\n"
        formatted_string += "\n" + "-"*40 + "\n"

    return formatted_string

def get_reference(feedback, submission_text):
    if (feedback["index_start"] is not None) and (feedback["index_end"] is not None):
        return submission_text[feedback["index_start"]:feedback["index_end"]]
    return submission_text
