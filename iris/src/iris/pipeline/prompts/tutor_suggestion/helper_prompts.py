def post_summary_prompt():

    summary_prompt: str = """
Summarize and rewrite the post and the answers, NEVER answer any question or give any suggestion. Also check if the post
is a question.
The initial post is: {post_content} by user {post_user_id}. Leave the user id out of the summary, but use it if
there are answers to identify the user in the thread as he might add context or additional information to his post.
In the thread of this post there are already {num_answers} answers.
The answers are:

```ANSWERS
{answers_content}
```

Important rules you must follow:
1. Summarize and rewrite the post and the answers, NEVER answer any question or give any suggestion.
2. Do NOT add any information that is not mentioned in the post, if the post is a question DON'T ANSWER IT!
3. If there are no answers in the thread, nothing that is additionally provided, just summarize the post.
4. Always be precise with your summary and rewriting don't forget any information that is needed for answering.
5. If a question is answered in the thread, you must include the question clearly marked as a question and the answer
in the summary. The question must be explicitly stated in the summary, and the answer must be explicitly stated in the
summary. If the post is the question, state that it is asked and then add the answer if there is one. If the question
is answered by multiple answers, you must include all the answers in the summary.
6. You must always with no exception return your result as a JSON consisting of the summary of the post in the form:
{{"summary": "<summary>", "is_question": "<is_question>"}}.
Never return the JSON with other keys or values, just the summary and if the post is a question. is_question is yes
or no!
"""

    return summary_prompt


def question_answered_prompt():
    return """You are a discussion classification assistant. Your task is to verify whether a question asked in the
following summarized discussion has already been answered correctly. Only perform this verification task—nothing else.

Discussion:
{thread_summary}

Instructions:
- If the question has been answered correctly in the discussion, respond with: yes
- If the question is not answered or answered incorrectly, respond with: no
"""
