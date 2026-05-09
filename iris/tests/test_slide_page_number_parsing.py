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
    assert LectureUnitPageIngestionPipeline.parse_slide_page_number(None) == -1


def test_parse_slide_page_number_keeps_large_values():
    assert LectureUnitPageIngestionPipeline.parse_slide_page_number("2026") == 2026


class _FakeRect:
    height = 1000


class _FakePage:
    def __init__(self, words, number=0):
        self._words = words
        self.rect = _FakeRect()
        self.number = number

    def get_text(self, mode):
        assert mode == "words"
        return self._words


def test_extract_slide_page_number_from_text_prefers_footer_candidates():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    page = _FakePage(
        [
            (100, 80, 160, 100, "2026", 0, 0, 0),
            (280, 930, 320, 960, "12", 0, 1, 0),
        ]
    )

    assert pipeline.extract_slide_page_number_from_text(page) == 12


def test_extract_slide_page_number_from_text_ignores_body_numbers():
    pipeline = LectureUnitPageIngestionPipeline.__new__(
        LectureUnitPageIngestionPipeline
    )
    page = _FakePage([(280, 420, 320, 450, "12", 0, 1, 0)])

    assert pipeline.extract_slide_page_number_from_text(page) == -1
