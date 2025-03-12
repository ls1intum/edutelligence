from iris.domain.lecture.lecture_unit_dto import LectureUnitDTO


def lecture_unit_summary_prompt(
    lecture_unit_dto: LectureUnitDTO, lecture_unit_segment_summary: str
):
    return f"""
        You are an excellent tutor with deep expertise in computer science and practical applications,
        teaching at the university level.
        Summaries of the lecture {lecture_unit_dto.lecture_name} in the course {lecture_unit_dto.course_name} \
        will be given to you.
        Please accurately follow the instructions below.
        1. Summarize the combined information in a clear and accurate manner.
        2. Do not add additional information.
        3. Only answer in complete sentences.
        This is summary of the lecture:
        {lecture_unit_segment_summary}
    """
