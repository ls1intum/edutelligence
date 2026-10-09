"""Tests for the deck language detection of the lecture page pipeline."""

import os
import subprocess  # nosec B404 - runs this interpreter on a fixed script
import sys
from pathlib import Path

_IRIS_ROOT = Path(__file__).resolve().parent.parent

# Runs in a fresh interpreter: in the test process another test may already have
# loaded the langdetect profiles, which would hide the race this guards against.
_PARALLEL_FIRST_USE = """
import threading
import iris.pipeline.pipeline  # noqa: F401
from iris.pipeline.lecture_ingestion_pipeline import detect_course_language

pages = [
    "Graphs: introduction. A graph has vertices and edges. Edges can be directed "
    "or undirected. Breadth first search visits the neighbours level by level, "
    "and depth first search follows one path as deep as it can before it goes back."
]
results = []
threads = [
    threading.Thread(target=lambda: results.append(detect_course_language(pages)))
    for _ in range(16)
]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print(sorted(set(results)))
"""


def test_parallel_first_detections_agree():
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(_IRIS_ROOT / "src")
    environment.setdefault(
        "APPLICATION_YML_PATH", str(_IRIS_ROOT / "application.example.yml")
    )
    completed = subprocess.run(  # nosec B603 - fixed script, no user input
        [sys.executable, "-c", _PARALLEL_FIRST_USE],
        capture_output=True,
        text=True,
        env=environment,
        cwd=_IRIS_ROOT,
        timeout=120,
        check=True,
    )
    assert completed.stdout.strip().splitlines()[-1] == "['en']"
