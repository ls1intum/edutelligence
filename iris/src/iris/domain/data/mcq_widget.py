"""Rendering of quiz widgets and other structured content from the chat history as text.

Artemis stores a generated multiple-choice question as JSON content of Iris' message, an
``mcq`` or an ``mcq-set`` object, and sends it back in the history of every later run. The agent
reads text only, so the widget is described here. A message that carries nothing but a widget must
still make a usable history entry: failing on it would fail every later message of the chat.
"""

import json
from typing import Any

# Bounds what one history entry can cost in the prompt, whatever the JSON holds.
MAX_DESCRIPTION_CHARS = 4_000


def _clip(text: str) -> str:
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    return text[:MAX_DESCRIPTION_CHARS] + " [...]"


def _describe_question(question: Any, number: int | None) -> str | None:
    if not isinstance(question, dict) or not isinstance(question.get("question"), str):
        return None
    label = "Question" if number is None else f"Question {number}"
    lines = [f"{label}: " + question["question"]]
    correct_letter = None
    options = question.get("options")
    for index, option in enumerate(options if isinstance(options, list) else []):
        if not isinstance(option, dict) or not isinstance(option.get("text"), str):
            continue
        letter = chr(ord("A") + index) if index < 26 else str(index + 1)
        lines.append(f"{letter}) " + option["text"])
        if option.get("correct") is True and correct_letter is None:
            correct_letter = letter
    if correct_letter is not None:
        lines.append(f"Correct answer: {correct_letter}")
    explanation = question.get("explanation")
    if isinstance(explanation, str) and explanation.strip():
        lines.append(f"Explanation: {explanation}")
    return "\n".join(lines)


def describe_json_content(content: Any) -> str:
    """Describe the JSON content of a history message for the agent.

    A quiz widget becomes its question or questions with the options, the correct answer and the
    explanation, which the widget shows to the student once they have answered. Any other JSON is
    kept as compact text, so that no stored content can break a pipeline run.

    Args:
        content: The parsed JSON content of the message.

    Returns:
        The text the agent reads in place of the content, at most about 4000 characters.
    """
    if isinstance(content, dict):
        questions = None
        if content.get("type") == "mcq-set" and isinstance(
            content.get("questions"), list
        ):
            questions = [
                _describe_question(question, number)
                for number, question in enumerate(content["questions"], start=1)
            ]
        elif content.get("type") == "mcq" or "question" in content:
            questions = [_describe_question(content, None)]
        if questions and all(questions):
            return _clip(
                "[Interactive quiz shown to the student; the widget reveals the correct "
                "answer and the explanation after the student answers]\n\n"
                + "\n\n".join(questions)
            )
    try:
        compact = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        compact = str(content)
    return _clip(f"[Structured content] {compact}")
