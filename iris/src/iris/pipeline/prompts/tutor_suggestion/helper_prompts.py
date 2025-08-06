from iris.domain.data.post_dto import PostDTO


def post_summary_prompt(post: PostDTO):

    summary_prompt: str = f"""
Summarize and rewrite the post and the answers, NEVER answer any question or give any suggestion. Also check if the post
is a question.
The initial post is: {post.content} by user {post.user_id}. Leave the user id out of the summary, but use it if
there are answers to identify the user in the thread as he might add context or additional information to his post.
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


def lecture_summary_prompt():
    return """You are an expert in lecture content summaries. You are very good in getting the relevant information
for a discussion out of the provided lecture content. Based on the provided lecture transcriptions, summarize the\
 key points relevant to the following discussion. Clearly identify essential concepts, explanations, examples, and\
 instructions mentioned in the lecture content. Maintain clarity and conciseness. If the lecture content is not related\
 to the discussion, state that explicitly.
 
```LECTURE CONTENT
{lecture_content}
```

```DISCUSSION SUMMARY:
{summary_text}
```

For all relevant information get the relevant pages or time stamps, they are very important!
"""
