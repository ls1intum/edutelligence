def session_title_generation_prompt():
    return """ You are a helpful assistant that creates short, descriptive titles for conversations.
        Write a short, descriptive chat title based on a single user message and a reply.
        Requirements:
        - 2–5 words
        - No quotes, no emojis
        - No ending punctuation
        - Sentence case (capitalize first word only unless proper noun)
        - Focus on the core topic of the user message
        - The title MUST be in the same language as the user message and assistant reply

        Return ONLY the title text, nothing else.
        User: {first_user_msg}

        Assistant: {llm_response}
        """
