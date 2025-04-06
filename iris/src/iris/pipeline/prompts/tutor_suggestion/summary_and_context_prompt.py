from iris.domain.data.post_dto import PostDTO


def summary_and_context_prompt(post: PostDTO):
    post_prompt: str = f"""
You are an excellent chat summarizer of student question.
Your task is to summarize the question asked in the post.
The post has a initial question a thread with answers by other students, the questionare or tutors.
Those answers are also important as they add more information and context to the question.
The posts question is: {post.content} by user {post.user_id}
"""
    answers_promt: str = ""
    if len(post.answers) != 0:
        answers_promt += f"""
In the thread of this post there are already {len(post.answers)} answers.
When summarizing those answers look of answers of the user with id {post.user_id} as
those answers might add more context to the question asked in the post.
The answers are:\n
"""
        for i in range(len(post.answers)):
            answer = post.answers[i]
            if answer is not None:
                answers_promt += f"{answer.content} by {answer.user_id}\n"
    context_prompt: str = f"""
Next add context to the question asked in the post.
For further valuation you need to put the question asked into categories.
Possible categories are: EXERCISE, LECTURE, ORGANIZATION, SPAM.
The definitions are below, I will also add examples for better understanding:
- EXERCISE: A question is an exercise question if the user asks specifically about a programming exercise
Examples for EXERCISE:
1. The test xyz always fails even if I use the algorithm used in the lecture, what might be wrong?
- LECTURE: A question is a lecture question if the user asks specifically about lecture contents or something the 
professor said
Examples for LECTURE:
1. The professor talked about possible other algorithms that are with complexity O(1) what are other examples?
- ORGANIZATION: A question is an organizational question if the user asks specifically about organizational questions
Examples for ORGANIZATION:
1. When is the retake exam, I can't find any information in the slides.
2. I am matched for tutor group 2, where can I see which room I have to go to?
- SPAM: A spam question is a question with no real use:
Examples for SPAM:
1. 
"""

    result_display_prompt: str = """
Important rules you shall follow:
1. Do NOT add any information that is not asked in the post.
2. Always be precise with your summary don't forget any information that is need for answering.
3. Your last sentence should be a JSON consisting of the category and the summary of the post.
"""

    return (post_prompt
            + answers_promt
            + context_prompt
            + result_display_prompt)