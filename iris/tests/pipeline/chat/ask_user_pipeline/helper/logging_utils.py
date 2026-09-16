"""Structured result logging for the ask_user_pipeline / assess_user_answer_pipeline
LLM tests.

Every test class writes the data into its own CSV file under iris/test-results/
(gitignored). One test run only ever exercises the exercise currently
selected by helper.exercises.ACTIVE_EXERCISE, so file names are suffixed
with a slug of that exercise's title to avoid the two exercises silently
overwriting each other's log.
"""

import csv
import re
from pathlib import Path
from threading import Lock

# Central switch: flip to False to disable all structured result logging
# performed by these tests, without touching the individual test files.
ENABLE_TEST_RESULT_LOGGING = True

# Separate switch for the manual-annotation CSV (question text only, no
# verdicts), so it can be turned on for a dedicated annotation run without
# also toggling the rest of the structured result logging above.
ENABLE_MANUAL_ANNOTATION_LOGGING = True

# iris/tests/pipeline/chat/ask_user_pipeline/helper/logging_utils.py -> iris/
_RESULTS_DIR = Path(__file__).resolve().parents[5] / "test-results"


def exercise_slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug or "exercise"


class ResultLog:
    """Appends rows to a CSV file under iris/test-results/, one file per
    test class (and, where a table needs it, per sub-topic). A leading
    comment line (e.g. the question a set of scenarios responds to) can be
    written once before the header. No-ops entirely when
    ENABLE_TEST_RESULT_LOGGING is False.
    """

    def __init__(self, filename: str, header: list[str], comment: str | None = None):
        self.enabled = ENABLE_TEST_RESULT_LOGGING
        self._lock = Lock()
        if not self.enabled:
            return

        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        self._path = _RESULTS_DIR / filename

        with self._path.open("w", newline="", encoding="utf-8") as f:
            if comment:
                f.write(f"# {comment}\n")
            csv.writer(f).writerow(header)

    def append_row(self, row: list) -> None:
        if not self.enabled:
            return
        with self._lock:
            with self._path.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(row)
