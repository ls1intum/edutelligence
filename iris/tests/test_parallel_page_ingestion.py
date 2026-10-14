"""Slides and slide segments of a lecture unit go to the LLM several at a time, with the same result."""

import base64
import threading
import time
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.custom_exceptions import IngestionCancelledException
from iris.config import settings
from iris.domain.data.slide_vision_dto import SlideVisionDTO
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline
from iris.pipeline.lecture_unit_segment_summary_pipeline import (
    LectureUnitSegmentSummaryPipeline,
)

# pylint: disable=protected-access


class _Concurrency:
    """Counts how many calls run at the same time."""

    def __init__(self):
        self._lock = threading.Lock()
        self.running = 0
        self.peak = 0

    def __enter__(self):
        with self._lock:
            self.running += 1
            self.peak = max(self.peak, self.running)

    def __exit__(self, *_exc):
        with self._lock:
            self.running -= 1


def _doc(page_count: int):
    pages = []
    for number in range(page_count):
        page = MagicMock()
        page.get_text.return_value = f"text of page {number}"
        page.get_pixmap.return_value.tobytes.return_value = f"image {number}".encode()
        pages.append(page)
    return SimpleNamespace(page_count=page_count, load_page=lambda n: pages[n])


def _page_pipeline(cancel_event=None):
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.cancel_event = cancel_event or Event()
    pipeline.callback = MagicMock()
    pipeline.course_language = "en"
    return pipeline


def _slide_dto():
    return SimpleNamespace(lecture_unit_id=7, lecture_name="Software Engineering")


def test_pages_are_interpreted_side_by_side_and_returned_in_page_order():
    pipeline = _page_pipeline()
    concurrency = _Concurrency()
    contexts = {}

    def interpret(img_base64, last_page_content, *_args):
        with concurrency:
            time.sleep(0.05)
        page = int(base64.b64decode(img_base64).decode().split()[-1])
        contexts[page] = last_page_content
        return SlideVisionDTO(
            display_page_number=page + 1, academic_description=f"slide {page}"
        )

    pipeline.interpret_image = interpret
    pipeline.merge_page_content_and_image_interpretation = (
        lambda text, description: f"{text} + {description}"
    )
    with patch.object(settings.lecture_ingestion, "vision_concurrency", 3):
        results = pipeline._interpret_pages(
            _doc(7), [f"text of page {n}" for n in range(7)], _slide_dto()
        )

    assert results == [(n + 1, f"text of page {n} + slide {n}") for n in range(7)]
    assert concurrency.peak == 3
    assert contexts[0] == ""
    assert contexts[4] == "text of page 3"
    progress = [
        c.kwargs["stage_progress"] for c in pipeline.callback.update.call_args_list
    ]
    assert progress == list(range(1, 8))


def test_a_failing_page_fails_the_run_and_starts_no_further_pages():
    pipeline = _page_pipeline()
    started = []

    def interpret(img_base64, *_args):
        page = int(base64.b64decode(img_base64).decode().split()[-1])
        started.append(page)
        if page == 0:
            raise RuntimeError("vision failed")
        time.sleep(0.05)
        return SlideVisionDTO(display_page_number=-1, academic_description="x")

    pipeline.interpret_image = interpret
    pipeline.merge_page_content_and_image_interpretation = lambda text, _d: text
    with patch.object(settings.lecture_ingestion, "vision_concurrency", 2):
        with pytest.raises(RuntimeError, match="vision failed"):
            pipeline._interpret_pages(_doc(10), ["t"] * 10, _slide_dto())

    assert len(started) < 10


def test_a_cancelled_run_stops_before_the_next_page():
    cancel = Event()
    pipeline = _page_pipeline(cancel)

    def interpret(*_args):
        cancel.set()
        return SlideVisionDTO(display_page_number=-1, academic_description="x")

    pipeline.interpret_image = interpret
    pipeline.merge_page_content_and_image_interpretation = lambda text, _d: text
    with patch.object(settings.lecture_ingestion, "vision_concurrency", 1):
        with pytest.raises(IngestionCancelledException):
            pipeline._interpret_pages(_doc(5), ["t"] * 5, _slide_dto())


def test_segment_summaries_run_side_by_side_and_keep_segment_order():
    pipeline = object.__new__(LectureUnitSegmentSummaryPipeline)
    pipeline.cancel_event = Event()
    pipeline.callback = MagicMock()
    pipeline.lecture_unit_dto = SimpleNamespace(lecture_unit_id=7)
    concurrency = _Concurrency()

    def create_summary(*args):
        slides = args[1]
        with concurrency:
            time.sleep(0.05)
        return f"summary of {slides[0]}"

    pipeline._create_summary = create_summary
    segments = [(n, n, [], [f"slide {n}"]) for n in range(6)]
    with patch.object(settings.lecture_ingestion, "segment_summary_concurrency", 3):
        summaries = pipeline._summarize_segments(segments)

    assert summaries == [f"summary of slide {n}" for n in range(6)]
    assert concurrency.peak == 3
    progress = [
        c.kwargs["stage_progress"] for c in pipeline.callback.update.call_args_list
    ]
    assert progress == list(range(1, 7))


def test_each_segment_summary_counts_the_tokens_of_its_own_call():
    pipeline = object.__new__(LectureUnitSegmentSummaryPipeline)
    pipeline.lecture_unit_dto = SimpleNamespace(
        lecture_unit_id=7, lecture_name="SE", course_name="Course"
    )
    pipeline.llm = SimpleNamespace(request_handler="handler", completion_args="args")
    pipeline.tokens = []
    models = []

    def build_model(request_handler, completion_args):
        model = SimpleNamespace(tokens=SimpleNamespace(pipeline=None, call=len(models)))
        models.append((request_handler, completion_args))
        return model

    chain = MagicMock()
    chain.invoke.return_value = "summary"
    with patch(
        "iris.pipeline.lecture_unit_segment_summary_pipeline.IrisLangchainChatModel",
        side_effect=build_model,
    ), patch(
        "iris.pipeline.lecture_unit_segment_summary_pipeline.ChatPromptTemplate"
    ) as template:
        template.from_messages.return_value.__or__.return_value.__or__.return_value = (
            chain
        )
        first = pipeline._create_summary([], [], None)
        second = pipeline._create_summary([], [], None)

    assert first == second == "summary"
    assert models == [("handler", "args"), ("handler", "args")]
    assert [t.call for t in pipeline.tokens] == [0, 1]


def test_a_run_cancelled_during_a_merge_starts_no_further_page():
    cancel = Event()
    pipeline = _page_pipeline(cancel)
    merges = []

    def merge(text, *_args):
        merges.append(text)
        cancel.set()
        return text

    pipeline.interpret_image = lambda *_args: SlideVisionDTO(
        display_page_number=-1, academic_description="x"
    )
    pipeline.merge_page_content_and_image_interpretation = merge
    with patch.object(settings.lecture_ingestion, "vision_concurrency", 1):
        with pytest.raises(IngestionCancelledException):
            pipeline._interpret_pages(_doc(6), ["t"] * 6, _slide_dto())

    assert len(merges) == 1


def test_a_page_without_a_vision_description_keeps_its_text_without_a_merge():
    pipeline = _page_pipeline()
    pipeline.interpret_image = lambda *_args: SlideVisionDTO(
        display_page_number=3, academic_description=""
    )
    pipeline.merge_page_content_and_image_interpretation = MagicMock()

    results = pipeline._interpret_pages(_doc(1), ["only text"], _slide_dto())

    assert results == [(3, "only text")]
    pipeline.merge_page_content_and_image_interpretation.assert_not_called()
