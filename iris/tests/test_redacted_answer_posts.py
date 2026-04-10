import json

from iris.domain.data.answer_post_dto import AnswerPostDTO
from iris.domain.data.post_dto import PostDTO
from iris.pipeline.shared.utils import (
    REDACTED_ANSWER_PLACEHOLDER,
    format_post_discussion,
)


def _answer(
    answer_id: int, user_id: int, content, redacted: bool = False
) -> AnswerPostDTO:
    return AnswerPostDTO.model_validate(
        {"id": answer_id, "content": content, "userID": user_id, "redacted": redacted}
    )


def _post(answers: list[AnswerPostDTO]) -> PostDTO:
    return PostDTO.model_validate(
        {
            "id": 1,
            "content": "How does X work?",
            "userID": 10,
            "answers": [a.model_dump(by_alias=True) for a in answers],
        }
    )


# ---------------------------------------------------------------------------
# AnswerPostDTO serialisation
# ---------------------------------------------------------------------------


def test_answer_post_dto_normal():
    data = {
        "id": 5,
        "content": "some text",
        "resolvesPost": False,
        "userID": 42,
        "redacted": False,
    }
    dto = AnswerPostDTO.model_validate(data)
    assert dto.content == "some text"
    assert dto.redacted is False


def test_answer_post_dto_redacted():
    data = {
        "id": 5,
        "content": None,
        "resolvesPost": False,
        "userID": 42,
        "redacted": True,
    }
    dto = AnswerPostDTO.model_validate(data)
    assert dto.content is None
    assert dto.redacted is True


def test_answer_post_dto_old_schema_defaults_redacted_false():
    """Old Artemis schema without the redacted field should default to False."""
    data = {"id": 5, "content": "some text", "resolvesPost": False, "userID": 42}
    dto = AnswerPostDTO.model_validate(data)
    assert dto.redacted is False


def test_answer_post_dto_redacted_json():
    raw = '{"id": 5, "content": null, "resolvesPost": false, "userID": 42, "redacted": true}'
    dto = AnswerPostDTO.model_validate(json.loads(raw))
    assert dto.redacted is True
    assert dto.content is None


# ---------------------------------------------------------------------------
# format_post_discussion (shared/utils.py)
# ---------------------------------------------------------------------------


def test_format_post_discussion_redacted_shows_placeholder():
    post = _post([_answer(2, 99, None, redacted=True)])
    result = format_post_discussion(post)
    assert REDACTED_ANSWER_PLACEHOLDER in result


def test_format_post_discussion_normal_shows_content():
    post = _post([_answer(2, 42, "Here is the answer.")])
    result = format_post_discussion(post)
    assert "Here is the answer." in result
    assert REDACTED_ANSWER_PLACEHOLDER not in result


def test_format_post_discussion_mixed():
    post = _post(
        [
            _answer(2, 42, "Visible answer."),
            _answer(3, 99, None, redacted=True),
        ]
    )
    result = format_post_discussion(post)
    assert "Visible answer." in result
    assert REDACTED_ANSWER_PLACEHOLDER in result


def test_format_post_discussion_no_answers():
    post = _post([])
    result = format_post_discussion(post)
    assert "No previous responses yet." in result
    assert REDACTED_ANSWER_PLACEHOLDER not in result


def test_format_post_discussion_with_user_ids_redacted():
    post = _post([_answer(2, 99, None, redacted=True)])
    result = format_post_discussion(post, include_user_ids=True)
    assert REDACTED_ANSWER_PLACEHOLDER in result
    assert "by user 99" in result
