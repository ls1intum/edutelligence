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
Next, add context to the question asked in the post.
Your task is to help categorize the question and add meaningful context for better understanding.
There are five possible categories a post can belong to: EXERCISE, LECTURE, EXERCISE_LECTURE, ORGANIZATION, SPAM.
Use the following definitions and examples to determine the category.

 - EXERCISE: These are questions directly related to solving a programming or homework exercise.
   Typical characteristics:
   • Mentions failing tests, specific exercise numbers, or programming issues.
   • Asks for help with code, debugging, or logic errors.
   Examples:
   1. "The test `calculate_max` always fails. I've tried the O(n) algorithm shown in class."
   2. "I get a null pointer exception when running my solution for Exercise 5."

 - LECTURE: These questions relate to lecture content, concepts explained by the professor, or theoretical topics.
   Typical characteristics:
   • Mentions lecture slides, terminology, or algorithms discussed in class.
   • Asks for clarifications or further examples.
   Examples:
   1. "In the lecture, the professor said Dijkstra's algorithm is greedy. Can you explain why?"
   2. "What is the difference between depth-first and breadth-first search as discussed last week?"

 - EXERCISE_LECTURE: These questions combine both aspects of exercises and lecture content.
   Typical characteristics:
   • The question refers to an exercise or implementation but also explicitly ties back to concepts from lectures.
   • Often indicates they tried an approach taught in class or are unsure how lecture theory applies to their code.
   Examples:
   1. "I’m trying to solve Exercise 7 using the greedy algorithm from last week’s lecture, but my output is still incorrect. What might I be missing?"
   2. "The code from class on Dijkstra’s algorithm isn’t working in the exercise. Could it be because of the graph input?"
 
 - ORGANIZATION: These are logistical or course-structure related questions.
   Typical characteristics:
   • Mentions deadlines, exam dates, group assignments, or location/timing of classes.
   • Often uses phrases like 'when', 'where', 'how to register'.
   Examples:
   1. "When is the retake exam scheduled?"
   2. "I’m in tutor group 4, where do I find the Zoom link?"

 - SPAM: These posts contain no meaningful content or are irrelevant.
   Typical characteristics:
   • Contain only greetings, nonsense, or off-topic content.
   • Do not ask for help or clarification.
   Examples:
   1. "Hello???"
   2. "asdfghjkl"
   3. "Just testing this."
 
 - NO_CATEGORY: These are rare cases where the post does not clearly fit any of the other categories.
   Typical characteristics:
   • The message might be too vague, ambiguous, or off-topic without being full spam.
   • Could include personal reflections, system tests, or unclear intent.
   Examples:
   1. "I'm just wondering how everyone feels about the difficulty of this course."
   2. "Testing if the forum works."
   3. "No idea where to post this, just thinking out loud."
Your goal is to determine which category fits the post best and to summarize it appropriately.
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