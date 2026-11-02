"""Tests for disabling ONNX telemetry before native runtime initialization."""

import os
import subprocess  # nosec B404 - runs this interpreter on a fixed script
import sys
from pathlib import Path

import pytest

_IRIS_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("existing_value", [None, "0", ""])
def test_importing_iris_sets_telemetry_default_and_preserves_operator_value(
    existing_value,
):
    environment = dict(os.environ)
    for variable in ("CI", "GITHUB_ACTIONS", "ORT_DISABLE_TELEMETRY"):
        environment.pop(variable, None)
    environment["PYTHONPATH"] = str(_IRIS_ROOT / "src")
    if existing_value is not None:
        environment["ORT_DISABLE_TELEMETRY"] = existing_value

    completed = subprocess.run(  # nosec B603 - fixed script, no user input
        [
            sys.executable,
            "-c",
            "import os; import iris; print(os.environ['ORT_DISABLE_TELEMETRY'])",
        ],
        capture_output=True,
        text=True,
        env=environment,
        cwd=_IRIS_ROOT,
        timeout=30,
        check=True,
    )

    expected_value = "1" if existing_value is None else existing_value
    assert completed.stdout == expected_value + "\n"
