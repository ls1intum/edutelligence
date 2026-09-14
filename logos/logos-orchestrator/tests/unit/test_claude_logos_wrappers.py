"""Encoding and revision invariants of the claude-logos wrappers the UI serves.

The Windows wrapper is downloaded with Invoke-WebRequest and run by Windows
PowerShell 5.1, which reads a BOM-less .ps1 in the system ANSI code page: the
UTF-8 bytes of an em dash come back as mojibake and the script's own messages
stop being readable. The served .ps1 must therefore stay pure ASCII, and the
two wrappers are one tool with two front ends, so their revision constants
must stay in step.
"""

import re
from pathlib import Path

PUBLIC_DIR = Path(__file__).resolve().parents[3] / "logos-ui" / "public"
WINDOWS_WRAPPER = PUBLIC_DIR / "claude-logos.ps1"
POSIX_WRAPPER = PUBLIC_DIR / "claude-logos.sh"


def test_windows_wrapper_is_ascii_only():
    data = WINDOWS_WRAPPER.read_bytes()
    bad_lines = [
        (no, line.decode("ascii", "replace"))
        for no, line in enumerate(data.splitlines(), 1)
        if any(byte > 127 for byte in line)
    ]
    assert not bad_lines, (
        "claude-logos.ps1 must stay pure ASCII, Windows PowerShell 5.1 reads a "
        "BOM-less .ps1 in the system ANSI code page and mangles UTF-8 bytes:\n"
        + "\n".join(f"line {no}: {line}" for no, line in bad_lines[:10])
    )


def _revision(path: Path, pattern: str) -> int:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, f"no revision constant matching {pattern!r} in {path.name}"
    return int(match.group(1))


def test_wrapper_revisions_are_in_step():
    windows = _revision(WINDOWS_WRAPPER, r"^\$ClaudeLogosVersion\s*=\s*(\d+)")
    posix = _revision(POSIX_WRAPPER, r"^CLAUDE_LOGOS_VERSION=(\d+)")
    assert windows == posix, (
        f"claude-logos.ps1 declares revision {windows} but claude-logos.sh "
        f"declares {posix}; the two wrappers are one tool and the constants "
        "must be kept in step"
    )
