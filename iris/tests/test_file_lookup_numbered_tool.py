"""Tests for the line-numbered file_lookup tool factory.

``tests/conftest.py`` sets ``APPLICATION_YML_PATH`` before pipeline imports, so
importing the real factory here is safe (matching the other pipeline tests).
"""

from unittest.mock import MagicMock

from iris.tools.file_lookup_numbered import (
    create_tool_file_lookup_with_line_numbers,
)


def _tool(repository):
    callback = MagicMock()
    tool = create_tool_file_lookup_with_line_numbers(repository, callback)
    return tool, callback


def test_success_path_is_line_numbered_1_based():
    tool, callback = _tool({"F.java": "a\nb\nc"})
    assert tool("F.java") == "F.java:\n   1| a\n   2| b\n   3| c\n"
    callback.in_progress.assert_called_once_with("Looking into file F.java ...")


def test_numbering_starts_at_one_not_zero():
    tool, _ = _tool({"F.java": "first"})
    out = tool("F.java")
    assert out == "F.java:\n   1| first\n"
    assert "   0|" not in out


def test_empty_file_matches_stock_shape():
    # "".splitlines() -> [] -> empty body, same shape stock would return.
    tool, _ = _tool({"F.java": ""})
    assert tool("F.java") == "F.java:\n\n"


def test_file_not_found_delegates_to_base():
    tool, callback = _tool({"F.java": "x"})
    assert tool("Other.java") == "File not found or does not exist in the repository."
    # Delegated to the stock tool, which still emits one progress callback.
    callback.in_progress.assert_called_once_with("Looking into file Other.java ...")


def test_no_repository_delegates_to_base():
    tool, _ = _tool(None)
    assert tool("F.java") == (
        "No repository content available. File content cannot be retrieved."
    )


def test_tool_metadata_name_and_docstring_carry_the_contract():
    # B2 relies on LangChain exposing the inner callable's __name__ as the tool
    # name and its docstring as the tool description, so lock both in.
    tool, _ = _tool({"F.java": "x"})
    assert tool.__name__ == "file_lookup"
    assert tool.__doc__ is not None
    assert "line number" in tool.__doc__.lower()
    assert "NN|" in tool.__doc__
