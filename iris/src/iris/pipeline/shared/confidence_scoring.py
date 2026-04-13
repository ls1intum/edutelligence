import re

_LARGE_MODEL_FAMILIES = ("gpt-4", "gpt-5", "gpt-oss")

_SIZE_TOKEN_RE = re.compile(r"(\d+)\s*b\b", re.IGNORECASE)

_ANSWER_PREFIX_RE = re.compile(
    r"^(?:answer|guess)\s*:\s*",
    re.IGNORECASE,
)

_PROBABILITY_LINE_RE = re.compile(
    r"(?:probability|confidence|p)\s*:\s*(-?\d+(?:\.\d+)?)(\s*%)?",
    re.IGNORECASE,
)


def is_large_model(model_id: str) -> bool:
    """Return True if the model should use the combo confidence prompt.

    A model is considered large when:
    - It belongs to a known large-model family (GPT-4, GPT-5, gpt-oss), OR
    - Its name contains a numeric parameter size ≥ 32 followed by "b"
      (e.g. "llama-3-70b", "codellama-34b", "mixtral-65b-instruct").
    Everything else is treated as small.
    """
    lower = model_id.lower()

    if any(family in lower for family in _LARGE_MODEL_FAMILIES):
        return True

    for match in _SIZE_TOKEN_RE.finditer(lower):
        if int(match.group(1)) >= 32:
            return True

    return False


def parse_confidence_response(raw_response: str) -> tuple[str, float]:
    """Extract (answer_text, probability) from a verbalized confidence response.

    Handles both large-model format (Guess: ... / Probability: ...) and
    small-model format (Answer: ... / Probability: ...).  Also accepts
    "Confidence:" and "P:" as alternatives to "Probability:", and values
    expressed as percentages (e.g. "85%" → 0.85).  The probability is
    clamped to [0.0, 1.0].

    If parsing fails for any reason this function returns (raw_response, 0.0)
    so that callers never receive an exception.  A score of 0.0 will be
    treated as below threshold and discarded by Artemis.
    """
    try:
        lines = raw_response.strip().splitlines()

        # Find the last line that matches a probability pattern.
        prob_line_index = None
        probability = 0.0
        for i in range(len(lines) - 1, -1, -1):
            m = _PROBABILITY_LINE_RE.search(lines[i])
            if m:
                prob_line_index = i
                raw_value = float(m.group(1))
                is_percent = bool(m.group(2) and m.group(2).strip() == "%")
                if is_percent:
                    probability = raw_value / 100.0
                else:
                    probability = raw_value
                probability = max(0.0, min(1.0, probability))
                break

        if prob_line_index is None:
            # No probability line found — safe fallback.
            return raw_response, 0.0

        # Everything before the probability line is the answer block.
        answer_lines = lines[:prob_line_index]

        # Strip the "Answer:" / "Guess:" prefix from the first line if present.
        if answer_lines:
            answer_lines[0] = _ANSWER_PREFIX_RE.sub("", answer_lines[0])

        answer_text = "\n".join(answer_lines).strip()

        # If nothing is left after stripping, fall back to the raw response.
        if not answer_text:
            answer_text = raw_response

        return answer_text, probability

    except Exception:  # pylint: disable=broad-except
        return raw_response, 0.0
