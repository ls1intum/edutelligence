def transcription_summary_prompt(lecture_name: str, chunk_content: str):
    return f"""
        You are an excellent tutor with deep expertise in computer science and practical applications, teaching at the university level.
        A snippet of the spoken content of one lecture of the lecture {lecture_name} will be given to you.
        Please accurately follow the instructions below.
        1. Summarize the information in a clear and accurate manner.
        2. Do not add additional information.
        3. Only answer in complete sentences.
        This is the text you should summarize:
        {chunk_content}
    """
