"""The Jinja2 environment for prompt templates.

Prompts are plain text for a language model, not HTML, so values are inserted
unescaped: an HTML-escaping environment turned a problem statement with
``List<Integer>`` or ``a < b`` into ``List&lt;Integer&gt;`` before the model saw
it. Untrusted text that is embedded as data goes through the ``as_data`` filter,
which wraps it in a named tag and neutralizes a closing tag inside it, so the
text cannot end the data block early.
"""

import os
from typing import Optional

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def as_data(value: Optional[str], tag: str) -> str:
    """Wrap untrusted text in ``<tag>`` ... ``</tag>`` that it cannot close."""
    text = "" if value is None else str(value)
    text = text.replace(f"</{tag}", f"<\\/{tag}")
    return f"<{tag}>\n{text}\n</{tag}>"


def prompt_environment(template_dir: str = TEMPLATE_DIR) -> Environment:
    """A template environment that inserts values as they are (no HTML escaping)."""
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=False,  # nosec B701 - prompts are model input, not HTML
    )
    environment.filters["as_data"] = as_data
    return environment
