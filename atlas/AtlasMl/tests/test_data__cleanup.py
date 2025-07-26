import pytest
from atlasml.ml.DataCleanup.data_cleanup import clean_problem_statements


@pytest.fixture
def sample_texts():
    return {
        "html_tags": "<p>Test content</p><div>More content</div>",
        "markdown_text": "# Heading\n**Bold text**\n*Italic*",
        "task_tags": "[task]Do this task[/task]",
        "markdown_links": "[Link text](http://example.com)",
        "math_expressions": "Here is math: $$x^2 + y^2 = z^2$$",
        "code_formatting": "Here is `inline code` and ```block code```",
        "html_styling": "<tt style='color:red'>Styled text</tt>",
        "special_chars": "Text with⎵special⎵spaces",
        "whitespace": "  Multiple    spaces  \n  New lines  \n",
        "code_blocks": "```python\ndef test():\n    pass\n```",
        "test_ids": "Test <testid>123</testid> reference",
        "mixed_content": """
        # Problem Statement
        [task]
        Calculate the following:
        $$1 + 1 = ?$$

        ```python
        def solution():
            return 1 + 1
        ```
        [/task]
        <testid>456</testid>
        """
    }


def test_html_tags_removal():
    text = "<p>Test content</p><div>More content</div>"
    result = clean_problem_statements(text)
    assert result == "Test content More content"


def test_markdown_conversion():
    text = "# Heading\n**Bold text**\n*Italic*"
    result = clean_problem_statements(text)
    assert "Heading" in result
    assert "Bold text" in result
    assert "Italic" in result


def test_task_tags_removal():
    text = "[task]Do this task[/task]"
    result = clean_problem_statements(text)
    assert result == "Do this task"


def test_markdown_links_removal():
    text = "[Link text](http://example.com)"
    result = clean_problem_statements(text)
    assert result == "Link text"


def test_math_expressions_removal():
    text = "Here is math: $$x^2 + y^2 = z^2$$"
    result = clean_problem_statements(text)
    assert result == "Here is math:"


def test_code_formatting_removal():
    text = "Here is `inline code` and ```block code```"
    result = clean_problem_statements(text)
    assert result == "Here is and"


def test_html_styling_removal():
    text = "<tt style='color:red'>Styled text</tt>"
    result = clean_problem_statements(text)
    assert result == "Styled text"


def test_special_chars_replacement():
    text = "Text with⎵special⎵spaces"
    result = clean_problem_statements(text)
    assert result == "Text with special spaces"


def test_whitespace_normalization():
    text = "  Multiple    spaces  \n  New lines  \n"
    result = clean_problem_statements(text)
    assert result == "Multiple spaces New lines"


def test_code_blocks_removal():
    text = "Before\n```python\ndef test():\n    pass\n```\nAfter"
    result = clean_problem_statements(text)
    assert result == "Before After"


def test_test_id_removal():
    text = "Test <testid>123</testid> reference"
    result = clean_problem_statements(text)
    assert result == "Test reference"


def test_mixed_content_cleaning():
    text = """
    # Problem Statement
    [task]
    Calculate the following:
    $$1 + 1 = ?$$

    ```python
    def solution():
        return 1 + 1
    ```
    [/task]
    <testid>456</testid>
    """
    result = clean_problem_statements(text)
    assert "Problem Statement" in result
    assert "Calculate the following:" in result
    assert "$$1 + 1 = ?$$" not in result
    assert "```python" not in result
    assert "<testid>456</testid>" not in result


def test_empty_input():
    assert clean_problem_statements("") == ""
    assert clean_problem_statements("   ") == ""


def test_none_input():
    with pytest.raises(TypeError):
        clean_problem_statements(None)


def test_non_string_input():
    with pytest.raises(TypeError):
        clean_problem_statements(123)


def test_nested_tags():
    text = "<div><p>Nested <span>content</span></p></div>"
    result = clean_problem_statements(text)
    assert result == "Nested content"


def test_multiple_code_blocks():
    text = "Text ```block1``` middle ```block2``` end"
    result = clean_problem_statements(text)
    assert result == "Text middle end"