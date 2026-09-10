"""Static guards for the macOS installer's supply-chain pins.

The installer executes upstream code on a machine that will hold other
people's prompts, so everything it executes or installs must be pinned to a
release tag and sha256-verified before use — including the installer's own
secondary fetches (scripts/lib.sh, the vllm-metal wheel, the vLLM core
wheel). These tests fail if a pin is dropped, an artifact stops being
verified, or a mutable (main / releases-latest) fetch slips back in.
"""

from __future__ import annotations

import re
from pathlib import Path

INSTALLER = Path(__file__).resolve().parent.parent / "scripts" / "install-macos.sh"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PINNED_VARS = (
    "VLLM_METAL_INSTALLER_SHA256",
    "VLLM_METAL_LIB_SHA256",
    "VLLM_METAL_WHEEL_SHA256",
    "VLLM_CORE_WHEEL_SHA256",
)


def _src() -> str:
    assert INSTALLER.is_file(), f"installer not found at {INSTALLER}"
    return INSTALLER.read_text(encoding="utf-8")


def _pinned_var(name: str) -> str:
    m = re.search(rf'^{name}="([^"]+)"', _src(), re.M)
    assert m, f"{name} missing from install-macos.sh"
    return m.group(1)


def test_release_ref_is_an_immutable_stable_tag() -> None:
    ref = _pinned_var("VLLM_METAL_REF")
    # No dev/nightly suffix: upstream prunes old dev releases (keeping only
    # the latest), so only a stable tag can be relied on to stay immutable.
    assert re.fullmatch(r"v\d+\.\d+\.\d+(\.post\d+)?", ref), f"VLLM_METAL_REF={ref!r} is not a stable release tag"


def test_every_pinned_artifact_has_a_sha256() -> None:
    for name in _PINNED_VARS:
        value = _pinned_var(name)
        assert _SHA256_RE.match(value), f"{name} is not a sha256: {value!r}"


def test_every_artifact_is_fetched_through_the_verifying_path() -> None:
    src = _src()
    for var in ("VLLM_METAL_LIB", "VLLM_METAL_WHEEL_URL", "VLLM_CORE_WHEEL_URL", "VLLM_METAL_INSTALLER"):
        assert (
            f'fetch_verified "${var}"' in src
        ), f"{var} is not downloaded via fetch_verified (download + sha256 check)"


def _executable_lines(src: str) -> list[str]:
    """Lines of the installer outside any heredoc body.

    The patch heredoc deliberately CONTAINS the old mutable URLs as
    search patterns — those must not be confused with live fetches.
    """
    lines = []
    heredoc_end: str | None = None
    for line in src.splitlines():
        if heredoc_end is not None:
            if line.strip() == heredoc_end:
                heredoc_end = None
            continue
        m = re.search(r"<<-?'?(\w+)'?\s*$", line)
        if m:
            heredoc_end = m.group(1)
            continue
        lines.append(line)
    return lines


def test_no_mutable_fetch_urls_remain() -> None:
    """main-branch and /releases/latest URLs must not appear in any
    executable line of the installer (comments are stripped)."""
    for line in _executable_lines(_src()):
        code = line.split("#", 1)[0]
        assert "releases/latest" not in code, f"mutable latest-release fetch: {line!r}"
        assert "/main/" not in code, f"mutable main-branch fetch: {line!r}"


def test_wheel_name_matches_the_pinned_release() -> None:
    ref = _pinned_var("VLLM_METAL_REF")
    wheel = _pinned_var("VLLM_METAL_WHEEL_NAME")
    assert wheel.startswith(
        f"vllm_metal-{ref.lstrip('v')}"
    ), f"VLLM_METAL_WHEEL_NAME={wheel!r} does not match VLLM_METAL_REF={ref!r}"


def test_version_floor_is_a_real_version() -> None:
    floor = _pinned_var("VLLM_METAL_MIN_VERSION")
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+)?", floor), f"VLLM_METAL_MIN_VERSION={floor!r}"
