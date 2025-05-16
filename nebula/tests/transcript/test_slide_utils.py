from unittest.mock import patch, MagicMock
from nebula.transcript.slide_utils import ask_gpt_for_slide_number


@patch("nebula.transcript.slide_utils.get_openai_client")
def test_ask_gpt_for_slide_number_valid(mock_client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Slide 12"
    mock_client.return_value = (
        MagicMock(
            chat=MagicMock(
                completions=MagicMock(create=MagicMock(return_value=mock_response))
            )
        ),
        "mock-deployment",
    )

    result = ask_gpt_for_slide_number("dummy_image_b64")
    assert result == 12


@patch("nebula.transcript.slide_utils.get_openai_client")
def test_ask_gpt_for_slide_number_unknown(mock_client):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "null"
    mock_client.return_value = (
        MagicMock(
            chat=MagicMock(
                completions=MagicMock(create=MagicMock(return_value=mock_response))
            )
        ),
        "mock-deployment",
    )

    result = ask_gpt_for_slide_number("dummy_image_b64")
    assert result is None
