def lecture_unit_segment_summary_prompt(
    lecture_name: str, course_name: str, transcription_content: str, slide_content: str
):
    return f"""
        You are an excellent tutor with deep expertise in computer science and practical applications,
        teaching at the university level.
        A snippet of the spoken content and the content of the matching slide, the professor is talking about, \
        of the lecture {lecture_name} in the course {course_name} will be given to you.
        Please accurately follow the instructions below.
        1. If either slide content or transcription content is empty only summarize the content you are given.
        2.1. Otherwise combine the information of the transcription and the slide
        2.2. Summarize the combined information in a clear and accurate manner.
        3. Do not add additional information.
        4. Only answer in complete sentences.
        This is the content of the transcription:
        {transcription_content}
        This is the content of the slide:
        {slide_content}
    """
