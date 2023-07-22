import pytest
from app.services.guidance_functions import truncate


@pytest.mark.parametrize(
    "history,max_length,expected",
    [
        ([], -2, []),
        ([], 0, []),
        ([], 2, []),
        ([1, 2, 3], 0, []),
        # Get the last n elements
        ([1, 2, 3], -4, [1, 2, 3]),
        ([1, 2, 3], -2, [2, 3]),
        # Get the first n elements
        ([1, 2, 3], 2, [1, 2]),
        ([1, 2, 3], 4, [1, 2, 3]),
    ],
)
def test_truncate(history, max_length, expected):
    assert truncate(history, max_length) == expected
