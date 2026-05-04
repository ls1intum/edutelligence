from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline


def test_parse_slide_page_number_with_integer_text():
    assert LectureUnitPageIngestionPipeline.parse_slide_page_number("12") == 12


def test_parse_slide_page_number_with_sentence():
    assert (
        LectureUnitPageIngestionPipeline.parse_slide_page_number(
            "The visible page number is 42."
        )
        == 42
    )


def test_parse_slide_page_number_without_number_returns_minus_one():
    assert LectureUnitPageIngestionPipeline.parse_slide_page_number("unknown") == -1
    assert LectureUnitPageIngestionPipeline.parse_slide_page_number("null") == -1
    assert LectureUnitPageIngestionPipeline.parse_slide_page_number("") == -1
    assert LectureUnitPageIngestionPipeline.parse_slide_page_number("-1") == -1
