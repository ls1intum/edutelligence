from iris.domain.data.post_dto import PostDTO


def summary_and_context_prompt(post: PostDTO):
    post_prompt: str = f"""
You are an excellent chat summarizer of student question.
Your task is to summarize the question asked in the post and add answers by other students.
The post has an initial question and a thread with answers by other students, the questionare or tutors.
Those answers are also important as they add more information and context to the question.
The posts question is: {post.content} by user {post.user_id}
"""
    answers_promt: str = ""
    if len(post.answers) != 0:
        answers_promt += f"""
In the thread of this post there are already {len(post.answers)} answers.
When summarizing those answers look of answers of the user with id {post.user_id} as
those answers might add more context to the question asked in the post. If the id differs from {post.user_id} then
those answers are not written by the author of the question.
Those other answer might be helpful to understand the question better. In some cases the question might be repetitive
and the answers might be similar to the question asked in the post. There is no need to add that other students said
they have the same problem or that they are also confused.
In the summary the answers should also be mentioned.
The answers are:\n
"""
        for i in range(len(post.answers)):
            answer = post.answers[i]
            if answer is not None:
                answers_promt += f"{answer.content} by {answer.user_id}\n"
    context_prompt: str = """
Next, add context to the question asked in the post.
Your task is to help categorize the question and add meaningful context for better understanding.
There are five possible categories a post can belong to: EXERCISE, LECTURE, EXERCISE_LECTURE, ORGANIZATION, SPAM.
Use the following definitions and examples to determine the category.

 - EXERCISE: These are questions directly related to solving a programming or text exercise.
   Typical characteristics:
    • Mentions failing tests, specific exercise numbers, or programming issues.
    • Asks for help with code, debugging, or logic errors.
    • Often includes code snippets or references to specific algorithms.
    • May mention specific programming languages or tools.
    • May include phrases like 'I tried', 'my code', or 'I need help with'.
    • May refer to specific test cases or expected outputs.
    • May ask for clarifications on exercise requirements or constraints.
    • May ask about how to understand something in the problem statement.
   Examples:
   1. "The test `calculate_max` always fails. I've tried the O(n) algorithm shown in class."
   2. "I get a null pointer exception when running my solution for Exercise 5."
   3. "I’m stuck on Exercise 3. Can someone explain how to implement the binary search algorithm?"
   4. "In the problem statement, it says to explain the time complexity. What are the key points I should include?"
   5. "Do I need to handle edge cases in the exercise? I’m not sure how to approach that."

 - LECTURE: These questions relate to lecture content, concepts explained by the professor, or theoretical topics.
   Typical characteristics:
    • Mentions lecture slides, terminology, or algorithms discussed in class.
    • Asks for clarifications or further examples.
    • Often includes phrases like 'in the lecture', 'the professor said', or 'can you explain'.
    • May refer to specific algorithms, data structures, or theoretical concepts mentioned in the lecture.
   Examples:
    1. "In the lecture, the professor said Dijkstra's algorithm is greedy. Can you explain why?"
    2. "What is the difference between depth-first and breadth-first search as discussed last week?"
    3. "I don’t understand the concept of dynamic programming. Can someone explain it with an example?"
    4. "The lecture slides mention a proof for the correctness of the algorithm. Can someone summarize it?"
    5. "Can you explain the difference between supervised and unsupervised learning as mentioned in the lecture?"

 - EXERCISE_LECTURE: These questions combine both aspects of exercises and lecture content.
   Typical characteristics:
    • The question refers to an exercise or implementation but also explicitly ties back to concepts from lectures.
    • Often indicates they tried an approach taught in class or are unsure how lecture theory applies to their code.
    • May ask for help with a specific exercise but also reference lecture content.
    • May include phrases like 'I used the algorithm from the lecture', 'the exercise is based on', or 'the lecture
    explained'.
   Examples:
    1. "I’m trying to solve Exercise 7 using the greedy algorithm from last week’s lecture, but my output is still
    incorrect. What might I be missing?"
    2. "The code from class on Dijkstra’s algorithm isn’t working in the exercise. Could it be because of the graph
    input?"
    3. "I’m using the binary search algorithm we learned in the lecture, but I can’t get it to work for Exercise 4.
    Can someone help me debug it?"
    4. "In the lecture, we discussed a sorting algorithm. I’m trying to implement it in Exercise 2, but I’m getting
    an error. Can someone help?"

 - ORGANIZATION: These are logistical or course-structure related questions.
   Typical characteristics:
    • Mentions deadlines, exam dates, group assignments, or location/timing of classes.
    • Often uses phrases like 'when', 'where', 'how to register'.
    • Asks about course organization, such as group assignments or exam schedules.
    • May include questions about course materials, such as where to find resources or how to access them.
    • May ask about the format of exams or assignments.
   Examples:
    1. "When is the retake exam scheduled?"
    2. "I’m in tutor group 4, where do I find the Zoom link?"
    3. "How do I register for the group assignment?"
    4. "Is there a deadline for submitting the project proposal?"
    5. "Where can I find the lecture notes for this week’s class?"

 - SPAM: These posts contain no meaningful content or are irrelevant.
   Typical characteristics:
    • Contain only greetings, nonsense, or off-topic content.
    • Do not ask for help or clarification.
    • May include random characters, symbols, or irrelevant links.
    • Often lack any context or connection to the course material.
    • May include excessive punctuation or gibberish.
    • May be promotional or advertising content.
   Examples:
    1. "Hello???"
    2. "asdfghjkl"
    3. "Just testing this."
    4. "Check out this link: www.spamlink.com"
    5. "I love this course!!!"
    6. "Buy cheap products here: www.spam.com"
    7. "This is a great course, but I think we should have more fun!"

 - NO_CATEGORY: These are rare cases where the post does not clearly fit any of the other categories.
   Typical characteristics:
    • The message might be too vague, ambiguous, or off-topic without being full spam.
    • Could include personal reflections, system tests, or unclear intent.
    • May contain questions or statements that are not directly related to the course material.
    • Often lacks specific context or clarity.
    • May include phrases like 'I’m just wondering', 'no idea where to post this', or 'just thinking out loud'.
   Examples:
    1. "I'm just wondering how everyone feels about the difficulty of this course."
    2. "Testing if the forum works."
    3. "No idea where to post this, just thinking out loud."
    4. "I’m not sure if this is the right place for this question."
    5. "Just a random thought about the course."
    6. "I’m not sure if this is relevant, but I wanted to share my experience."
Your goal is to determine which category fits the post best and to summarize it appropriately.
"""

    result_display_prompt: str = """
Important rules you shall follow:
1. Do NOT add any information that is not asked in the post.
2. Always be precise with your summary don't forget any information that is need for answering.
3. You must return your result as a JSON consisting of the category and the summary of the post.
"""

    return post_prompt + answers_promt + context_prompt + result_display_prompt
