from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO


def _escape_braces(text: str) -> str:
    """Escape curly braces for LangChain template compatibility."""
    return text.replace("{", "{{").replace("}", "}}")


def lecture_unit_summary_prompt(
    lecture_unit_dto: LectureUnitDTO, lecture_unit_segment_summary: str
):
    # Escape content that may contain curly braces (e.g., code snippets)
    safe_lecture = _escape_braces(lecture_unit_dto.lecture_name)
    safe_course = _escape_braces(lecture_unit_dto.course_name)
    safe_summary = _escape_braces(lecture_unit_segment_summary)
    return f"""
        You are an excellent tutor with deep expertise in computer science and practical applications,
        teaching at the university level.
        Summaries of the lecture {safe_lecture} in the course {safe_course} \
        will be given to you.
        Please accurately follow the instructions below.
        1. Summarize the combined information in a clear and accurate manner.
        2. Do not add additional information.
        3. Only answer in complete sentences.
        This is summary of the lecture:
        {safe_summary}
    """
