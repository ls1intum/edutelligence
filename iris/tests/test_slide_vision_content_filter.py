"""A slide the provider's content filter rejects must not fail the lecture unit it belongs to."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import BadRequestError, ContentFilterFinishReasonError

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.common.pyris_message import IrisMessageRole
from iris.domain.data.image_message_content_dto import ImageMessageContentDTO
from iris.domain.data.slide_vision_dto import SlideVisionDTO
from iris.llm.external.openai_chat import is_content_filter_error
from iris.pipeline.lecture_ingestion_pipeline import LectureUnitPageIngestionPipeline

# pylint: disable=protected-access

PREVIOUS_SLIDE = "Verbs are candidates for operations. Focus on this one first."


def _bad_request(code):
    request = httpx.Request("POST", "https://llm.example/v1/responses")
    return BadRequestError(
        "Error code: 400",
        response=httpx.Response(400, request=request),
        body={"code": code, "message": "The response was filtered"},
    )


def _answer(page=4, description="A UML class diagram."):
    return SimpleNamespace(
        token_usage=None,
        contents=[
            SimpleNamespace(
                text_content=(
                    f'{{"display_page_number": {page}, '
                    f'"academic_description": "{description}"}}'
                )
            )
        ],
    )


def _pipeline(chat):
    pipeline = object.__new__(LectureUnitPageIngestionPipeline)
    pipeline.tokens = []
    pipeline._append_tokens = MagicMock()
    pipeline.cancel_event = Event()
    pipeline.course_language = "en"
    pipeline.llm_chat = SimpleNamespace(chat=chat)
    return pipeline


def _texts(message):
    return [
        content.text_content
        for content in message.contents
        if hasattr(content, "text_content")
    ]


def test_instructions_and_slide_data_are_separate_messages():
    pipeline = _pipeline(MagicMock(return_value=_answer()))

    pipeline.interpret_image("aW1n", PREVIOUS_SLIDE, "Software Engineering", "en")

    system, user = pipeline.llm_chat.chat.call_args.args[0]
    assert system.sender == IrisMessageRole.SYSTEM
    assert "Software Engineering" in _texts(system)[0]
    assert "valid JSON" in _texts(system)[0]
    assert PREVIOUS_SLIDE not in _texts(system)[0]
    assert user.sender == IrisMessageRole.USER
    assert PREVIOUS_SLIDE in _texts(user)[0]
    assert any(isinstance(c, ImageMessageContentDTO) for c in user.contents)


def test_first_slide_says_there_is_no_previous_slide():
    pipeline = _pipeline(MagicMock(return_value=_answer(page=1)))

    pipeline.interpret_image("aW1n", "", "Software Engineering", "en")

    user = pipeline.llm_chat.chat.call_args.args[0][1]
    assert _texts(user) == ["There is no previous slide."]


def test_rejected_slide_is_retried_once_without_the_previous_slide():
    chat = MagicMock(side_effect=[_bad_request("content_filter"), _answer()])
    pipeline = _pipeline(chat)

    with patch("iris.pipeline.lecture_ingestion_pipeline.time.sleep") as mock_sleep:
        result = pipeline.interpret_image("aW1n", PREVIOUS_SLIDE, "Lecture", "en")

    assert result.academic_description == "A UML class diagram."
    assert chat.call_count == 2
    with_context, without_context = (call.args[0][1] for call in chat.call_args_list)
    assert PREVIOUS_SLIDE in _texts(with_context)[0]
    assert PREVIOUS_SLIDE not in _texts(without_context)[0]
    # The filter's verdict does not change with a delay.
    mock_sleep.assert_not_called()


def test_slide_rejected_even_without_context_keeps_its_text_without_failing():
    chat = MagicMock(side_effect=_bad_request("content_filter"))
    pipeline = _pipeline(chat)

    with patch("iris.pipeline.lecture_ingestion_pipeline.time.sleep") as mock_sleep:
        result = pipeline.interpret_image("aW1n", PREVIOUS_SLIDE, "Lecture", "en")

    assert result == SlideVisionDTO(display_page_number=-1, academic_description="")
    assert chat.call_count == 2
    mock_sleep.assert_not_called()


def test_rejected_first_slide_is_not_resent_unchanged():
    chat = MagicMock(side_effect=_bad_request("content_filter"))
    pipeline = _pipeline(chat)

    result = pipeline.interpret_image("aW1n", "", "Lecture", "en")

    assert result.academic_description == ""
    assert chat.call_count == 1


def test_a_filter_rejection_does_not_use_up_the_attempts_for_transient_errors():
    chat = MagicMock(
        side_effect=[
            RuntimeError("provider hiccup"),
            RuntimeError("provider hiccup"),
            _bad_request("content_filter"),
            _answer(),
        ]
    )
    pipeline = _pipeline(chat)

    with patch("iris.pipeline.lecture_ingestion_pipeline.time.sleep"):
        result = pipeline.interpret_image("aW1n", PREVIOUS_SLIDE, "Lecture", "en")

    assert result.academic_description == "A UML class diagram."


def test_other_bad_requests_still_fail_the_run():
    chat = MagicMock(side_effect=_bad_request("invalid_prompt"))
    pipeline = _pipeline(chat)

    with (
        patch("iris.pipeline.lecture_ingestion_pipeline.time.sleep"),
        pytest.raises(Exception, match="Slide interpretation failed"),
    ):
        pipeline.interpret_image("aW1n", PREVIOUS_SLIDE, "Lecture", "en")


def test_a_slide_without_description_keeps_its_extracted_text():
    pipeline = _pipeline(MagicMock(side_effect=_bad_request("content_filter")))
    pipeline.merge_page_content_and_image_interpretation = MagicMock()

    number, text = pipeline._interpret_and_merge_page(
        "aW1n", "raw slide text", PREVIOUS_SLIDE, "Lecture", 7
    )

    assert (number, text) == (-1, "raw slide text")
    pipeline.merge_page_content_and_image_interpretation.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_bad_request("content_filter"), True),
        (_bad_request("invalid_prompt"), False),
        (ContentFilterFinishReasonError(), True),
        (RuntimeError("content_filter"), False),
    ],
)
def test_is_content_filter_error(error, expected):
    assert is_content_filter_error(error) is expected
