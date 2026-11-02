"""Tests for disabling ONNX telemetry before native runtime initialization."""

import os
import subprocess  # nosec B404 - runs this interpreter on a fixed script
import sys
from pathlib import Path

import pytest

_IRIS_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = (
    "import os; "
    "import iris.pipeline.shared.global_search_intent_classifier; "
    "print(os.environ['ORT_DISABLE_TELEMETRY'])"
)


@pytest.mark.parametrize(
    ("existing_value", "expected_value"),
    [(None, "1"), ("", "1"), ("0", "0")],
)
def test_onnxruntime_import_sees_telemetry_default_and_operator_value(
    existing_value, expected_value
):
    environment = dict(os.environ)
    environment.pop("ORT_DISABLE_TELEMETRY", None)
    environment["PYTHONPATH"] = str(_IRIS_ROOT / "src")
    if existing_value is not None:
        environment["ORT_DISABLE_TELEMETRY"] = existing_value

    completed = subprocess.run(  # nosec B603 - fixed script, no user input
        [sys.executable, "-c", _SCRIPT],
        capture_output=True,
        text=True,
        env=environment,
        cwd=_IRIS_ROOT,
        timeout=60,
        check=True,
    )

    assert completed.stdout.splitlines()[-1] == expected_value
