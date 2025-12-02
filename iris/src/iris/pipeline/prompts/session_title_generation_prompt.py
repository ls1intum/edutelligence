def session_title_generation_prompt(user_language: str = "en"):
    """Generate session title prompt with language specification.

    Args:
        user_language: The user's preferred language ("en" or "de")
    """
    base_prompt = """ You are a helpful assistant that creates short, descriptive titles for conversations.
        Write a short, descriptive chat title based on a single user message and a reply.
        Requirements:
        - 2–5 words
        - No quotes, no emojis
        - No ending punctuation
        - Sentence case (capitalize first word only unless proper noun)
        - Focus on the core topic of the user message"""

    if user_language == "de":
        language_instruction = """
        - Generate the title in German"""
    else:
        language_instruction = """
        - Generate the title in English"""

    closing = """

        Return ONLY the title text, nothing else.
        User: {first_user_msg}

        Assistant: {llm_response}
        """

    return base_prompt + language_instruction + closing
