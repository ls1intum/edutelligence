def question_answered_prompt():
    return """You are a verification assistant. Your task is to verify if in this discussion an asked question
is already answered. Answer with yes or no if the question is already answered. The summarized
thread is the following:
{thread_summary}
Verify if a answer to a question is already present and also verify if the question is answered correctly.
If the question is answered correctly, answer with yes. If the question is not answered correctly, answer with no.
"""
