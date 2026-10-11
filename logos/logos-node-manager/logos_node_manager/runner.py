"""Process execution behind one seam.

The manager acts on the host only through the ``docker`` command line. Every call goes through a ``Runner``, so the
tests replace the real one with a fake and never need a Docker engine.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

logger = logging.getLogger(__name__)

# The exit codes that timeout(1) and a shell use for "timed out" and "command not found".
EXIT_TIMED_OUT = 124
EXIT_NOT_FOUND = 127


@dataclass(frozen=True)
class CommandResult:
    """Outcome of one command."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def tail(self, lines: int = 12) -> str:
        """The last lines of the output, for an error message."""
        if self.timed_out:
            return "the command timed out"
        text = "\n".join(part for part in (self.stderr.strip(), self.stdout.strip()) if part)
        return "\n".join(text.splitlines()[-lines:]) or f"exit code {self.returncode}"


class Runner(Protocol):
    def run(self, argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None) -> CommandResult: ...


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


class SubprocessRunner:
    """Runs the command on this machine.

    The environment of the process is the base, ``env`` is added on top. Only the command line is logged, and only at
    debug level: it holds file paths and image tags, and the environment, which can hold secrets, is never written.
    """

    def run(self, argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None) -> CommandResult:
        command = tuple(argv)
        logger.debug("run: %s", shlex.join(command))
        full_env = {**os.environ, **env} if env else None
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=full_env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(command, EXIT_TIMED_OUT, _as_text(exc.stdout), _as_text(exc.stderr), timed_out=True)
        except FileNotFoundError:
            return CommandResult(command, EXIT_NOT_FOUND, stderr=f"{command[0]}: command not found")
        return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)
