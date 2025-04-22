from iris.domain.data.post_dto import PostDTO


def post_summary_prompt(post: PostDTO):

    summary_prompt: str = f"""
    Summarize and rewrite the post and the answers, NEVER answer any question or give any suggestion.
    The initial post is: {post.content} by user {post.user_id}. Leave the user id out of the summary, but use it if there
    are answers to identify the user in the thread as he might add context or additional information to his post.
    In the thread of this post there are already {len(post.answers)} answers.
The answers are:
    """
    for i in range(len(post.answers)):
        answer = post.answers[i]
        if answer is not None:
            summary_prompt += f"{answer.content} by {answer.user_id}\n"
    summary_prompt += """
Important rules you must follow:
1. Summarize and rewrite the post and the answers, NEVER answer any question or give any suggestion.
2. Do NOT add any information that is not mentioned in the post, if the post is a question DON'T ANSWER IT!
3. If there are no answers in the thread, nothing that is additionally provided, just summarize the post.
4. Always be precise with your summary and rewriting don't forget any information that is needed for answering.
5. If a question is answered in the thread, you must include the question and the answer in the summary. The question 
must be explicitly stated in the summary, and the answer must be explicitly stated in the summary. If the post is the
question, state that it is asked and then add the answer if there is one. If the question is answered by multiple 
answers, you must include all the answers in the summary.
6. You must return your result as a JSON consisting of the summary of the post in the form {{"summary": "<summary>"}}.
Never return the JSON with other keys or values, just the summary.
    """

    return summary_prompt
