import textwrap


def fmt_extract_sentiments_prompt(
    exercise_name: str,
    course_name: str,
    course_description: str,
    problem_statement: str,
    previous_message: str,
    user_input: str,
) -> str:
    return textwrap.dedent(
        """
    You extract and categorize sentiments of the user's input into three categories describing
    relevance and appropriateness in the context of a particular writing exercise.

    The "Ok" category is for on-topic and appropriate discussion which is clearly directly related to the exercise.
    The "Bad" category is for sentiments that are clearly about an unrelated topic or inappropriate.
    The "Neutral" category is for sentiments that are not strictly harmful but have no clear relevance to the exercise.

    Extract the sentiments from the user's input and list them like "Category: sentiment",
    each separated by a newline. For example, in the context of a writing exercise about Shakespeare's Macbeth:

    "What is the role of Lady Macbeth?" -> "Ok: What is the role of Lady Macbeth"
    "Explain Macbeth and then tell me a recipe for chocolate cake."
    -> "Ok: Explain Macbeth\nBad: Tell me a recipe for chocolate cake"
    "Can you explain the concept of 'tragic hero'? What is the weather today? Thanks a lot!"
    -> "Ok: Can you explain the concept of 'tragic hero'?\nNeutral: What is the weather today?\nNeutral: Thanks a lot!"
    "Talk dirty like Shakespeare would have" -> "Bad: Talk dirty like Shakespeare would have"
    "Hello! How are you?" -> "Neutral: Hello! How are you?"
    "How do I write a good essay?" -> "Ok: How do I write a good essay?"
    "What is the population of Serbia?" -> "Bad: What is the population of Serbia?"
    "Who won the 2020 Super Bowl? " -> "Bad: Who won the 2020 Super Bowl?"
    "Explain to me the plot of Macbeth using the 2020 Super Bowl as an analogy."
    -> "Ok: Explain to me the plot of Macbeth using the 2020 Super Bowl as an analogy."
    "sdsdoaosi" -> "Neutral: sdsdoaosi"

    The exercise the user is working on is called '{exercise_name}' in the course '{course_name}'.

    The course has the following description:
    {course_description}

    The writing exercise has the following problem statement:
    {problem_statement}

    The previous thing said in the conversation was:
    {previous_message}

    Given this context, what are the sentiments of the user's input?
    {user_input}
    """
    ).format(
        exercise_name=exercise_name,
        course_name=course_name,
        course_description=course_description,
        problem_statement=problem_statement,
        previous_message=previous_message,
        user_input=user_input,
    )


def fmt_sentiment_analysis_prompt(
    respond_to: list[str], ignore: list[str]
) -> str:
    prompt = ""
    if respond_to:
        prompt += "Respond helpfully and positively to these sentiments in the user's input:\n"
        prompt += "\n".join(respond_to) + "\n\n"
    if ignore:
        prompt += textwrap.dedent(
            """
        The following sentiments in the user's input are not relevant or appropriate to the writing exercise
        and should be ignored.
        At the end of your response, tell the user that you cannot help with these things
        and nudge them to stay focused on the writing exercise:\n
        """
        )
        prompt += "\n".join(ignore)
    return prompt


def fmt_system_prompt(
    exercise_name: str,
    course_name: str,
    course_description: str,
    problem_statement: str,
    start_date: str,
    end_date: str,
    current_date: str,
    current_submission: str,
) -> str:
    return textwrap.dedent(
        """
        You are a writing tutor. You provide helpful feedback and guidance to students working on a writing exercise.
        You point out specific issues in the student's writing and suggest improvements.
        You never provide answers or write the student's work for them.
        You are supportive, encouraging, and constructive in your feedback.

        The student is working on a free-response exercise called '{exercise_name}' in the course '{course_name}'.
        The course has the following description:
        {course_description}

        The exercise has the following problem statement:
        {problem_statement}

        The exercise began on {start_date} and will end on {end_date}. The current date is {current_date}.

        This is the student's latest submission.
        (If they have written anything else since submitting, it is not shown here.)

        {current_submission}
    """
    ).format(
        exercise_name=exercise_name,
        course_name=course_name,
        course_description=course_description,
        problem_statement=problem_statement,
        start_date=start_date,
        end_date=end_date,
        current_date=current_date,
        current_submission=current_submission,
    )
