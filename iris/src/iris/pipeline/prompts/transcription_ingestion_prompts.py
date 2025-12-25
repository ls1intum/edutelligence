def _escape_braces(text: str) -> str:
    """Escape curly braces for LangChain template compatibility."""
    return text.replace("{", "{{").replace("}", "}}")


def transcription_summary_prompt(lecture_name: str, chunk_content: str):
    # Escape content that may contain curly braces (e.g., code snippets)
    safe_lecture = _escape_braces(lecture_name)
    safe_chunk = _escape_braces(chunk_content)
    return f"""
        You are an excellent tutor with deep expertise in computer science and practical applications,
        teaching at the university level.
        A snippet of the spoken content of one lecture of the lecture {safe_lecture} will be given to you.
        Please accurately follow the instructions below.
        1. Summarize the information in a clear and accurate manner.
        2. Do not add additional information.
        3. Only answer in complete sentences.
        This is the text you should summarize:
        {safe_chunk}
    """
