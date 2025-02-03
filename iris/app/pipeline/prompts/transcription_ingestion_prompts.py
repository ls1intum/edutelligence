def transcription_summary_prompt(lecture_name: str, chunk_content: str):
    return f"""
        You are a helpful assistant. A snippet of the spoken content of one lecture of the lecture {lecture_name} will be given to you, summarize the information without adding details and return only the summary nothing more.
        This is the text you should summarize:
        {chunk_content}
    """
