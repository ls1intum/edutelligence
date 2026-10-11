"""The one place that starts processes."""

from __future__ import annotations

import sys

from logos_node_manager.runner import EXIT_NOT_FOUND, EXIT_TIMED_OUT, CommandResult, SubprocessRunner


def test_output_and_exit_code_are_captured():
    result = SubprocessRunner().run(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"], timeout_s=20
    )

    assert result.returncode == 3
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert not result.ok


def test_the_extra_environment_is_added_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("NM_BASE", "base")

    result = SubprocessRunner().run(
        [sys.executable, "-c", "import os; print(os.environ['NM_BASE'], os.environ['NM_EXTRA'])"],
        timeout_s=20,
        env={"NM_EXTRA": "extra"},
    )

    assert result.stdout.strip() == "base extra"


def test_a_command_that_runs_too_long_is_killed():
    result = SubprocessRunner().run([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=0.5)

    assert result.timed_out
    assert result.returncode == EXIT_TIMED_OUT
    assert not result.ok


def test_a_missing_program_is_reported_not_raised():
    result = SubprocessRunner().run(["definitely-not-a-program"], timeout_s=5)

    assert result.returncode == EXIT_NOT_FOUND
    assert "command not found" in result.stderr


def test_the_tail_keeps_the_last_lines_of_the_output():
    result = CommandResult(("x",), 1, stdout="\n".join(f"line {n}" for n in range(30)), stderr="boom")

    tail = result.tail(3)

    assert tail.splitlines()[-1] == "line 29"
    assert len(tail.splitlines()) == 3


def test_a_timeout_has_its_own_message():
    assert CommandResult(("x",), EXIT_TIMED_OUT, timed_out=True).tail() == "the command timed out"
