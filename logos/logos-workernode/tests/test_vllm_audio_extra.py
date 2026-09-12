"""Static guards for the worker image's vLLM audio dependencies.

The speech-to-text endpoints (/v1/audio/transcriptions, /v1/audio/translations)
decode uploads through ``vllm.multimodal.media.audio.load_audio``, which has
exactly two backends and both are optional: ``soundfile`` (primary) and
``av``/PyAV (fallback, and the resampler to Whisper's 16 kHz). They ship solely
in vLLM's ``[audio]`` extra, so a pin without it turns *every* transcription
request into the same opaque 400, "Invalid or unsupported audio file." — the
failure mode of issue #925, which stood from the day Whisper support landed
because the pin never carried the extra.

The pin is not only hand-edited: ``.github/workflows/logos_update-vllm.yml``
rewrites it on every vLLM release. These tests therefore cover both halves of
the regression — the pin itself, and the automation that would otherwise strip
the extra on the next version bump (or, having read the extra as part of the
version, open the same update PR every hour).
"""

from __future__ import annotations

import re
from pathlib import Path

_WORKERNODE = Path(__file__).resolve().parent.parent
_REPO = _WORKERNODE.parent.parent

DOCKERFILE = _WORKERNODE / "Dockerfile"
COMPOSE_DEV = _WORKERNODE / "docker-compose.dev.yml"
WORKFLOW = _REPO / ".github" / "workflows" / "logos_update-vllm.yml"

# PEP 508 puts extras before the version specifier: "vllm[audio]==v0.29.0"
# parses, "vllm==v0.29.0[audio]" does not (pip rejects it as an invalid
# specifier). Asserting the shape — not just that "audio" appears somewhere —
# is what keeps the well-meant-but-unbuildable spelling out of the image.
_PIN_RE = re.compile(
    r'^ARG VLLM_PIP_SPEC="vllm(?P<extras>\[[^]]*\])?==(?P<version>v?[0-9][0-9a-z.]*)"$',
    re.M,
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file not found: {path}"
    return path.read_text(encoding="utf-8")


def _extras_of_pin() -> str:
    match = _PIN_RE.search(_read(DOCKERFILE))
    assert match, (
        "no parseable 'ARG VLLM_PIP_SPEC=\"vllm[extras]==<version>\"' default in the Dockerfile — "
        "extras must precede the version specifier (PEP 508)"
    )
    return match.group("extras") or ""


def test_worker_image_pins_vllm_with_the_audio_extra() -> None:
    extras = _extras_of_pin()
    assert "audio" in extras.strip("[]").split(","), (
        f"VLLM_PIP_SPEC extras are {extras or '(none)'}: without [audio] neither soundfile nor av is "
        "installed and every /v1/audio/transcriptions upload fails with 'Invalid or unsupported audio file.'"
    )


def test_dev_compose_default_pins_vllm_with_the_audio_extra() -> None:
    match = re.search(r"^\s*VLLM_PIP_SPEC:\s*\$\{VLLM_PIP_SPEC:-(?P<spec>[^}]+)\}", _read(COMPOSE_DEV), re.M)
    assert match, "docker-compose.dev.yml no longer defines a VLLM_PIP_SPEC default"
    assert "[audio]" in match.group("spec"), (
        f"dev compose default is {match.group('spec')!r} — a dev worker built from it cannot decode "
        "audio, so transcription bugs stay invisible until production"
    )


def _sed_substitution(assignment: str) -> tuple[re.Pattern[str], int]:
    """Return the ERE and capture group of a ``VAR=$(sed -nE 's/…/\\N/p' …)`` line.

    The pattern is compiled from the workflow verbatim, so these tests exercise
    the expression the workflow actually runs rather than a copy of it. ERE and
    Python's syntax coincide for the constructs used here (groups, ``?``,
    character classes, anchors).
    """
    match = re.search(
        rf"{assignment}=\$\(sed -nE 's/(?P<ere>[^/]+)/\\(?P<group>\d+)/p'",
        _read(WORKFLOW),
    )
    assert match, f"the update workflow no longer extracts {assignment} with a single sed substitution"
    return re.compile(match.group("ere")), int(match.group("group"))


def test_update_workflow_reads_the_version_past_any_extras() -> None:
    """A pin carrying extras must still compare equal to the PyPI version.

    Otherwise "Check whether an update is needed" reads the current pin as
    e.g. "0.29.0[audio]", never matches the release it just looked up, and the
    hourly schedule opens a fresh update PR on every single run.
    """
    pattern, group = _sed_substitution("CURRENT")
    cases = {
        'ARG VLLM_PIP_SPEC="vllm[audio]==v0.29.0"': "0.29.0",
        'ARG VLLM_PIP_SPEC="vllm==v0.29.0"': "0.29.0",  # control: bare pin still works
        'ARG VLLM_PIP_SPEC="vllm[audio]==v0.30.0rc1"': "0.30.0rc1",
        'ARG VLLM_PIP_SPEC="vllm[audio,video]==0.29.0"': "0.29.0",  # optional "v", several extras
    }
    for line, expected in cases.items():
        match = pattern.search(line)
        assert match, f"version not recognised in {line!r}"
        assert match.group(group) == expected, f"read {match.group(group)!r} instead of {expected!r} from {line!r}"

    # The live Dockerfile must be readable by the same expression, or the
    # workflow silently treats it as "no pin found" and bumps unconditionally.
    live = _PIN_RE.search(_read(DOCKERFILE))
    assert live is not None
    match = pattern.search(live.group(0))
    assert match and match.group(group) == live.group("version").lstrip("v")


def test_update_workflow_preserves_extras_when_bumping_the_pin() -> None:
    """The rewrite must re-attach the extras it found, not hardcode a bare pin."""
    workflow = _read(WORKFLOW)
    assert 'ARG VLLM_PIP_SPEC=\\"vllm==v$VERSION\\"' not in workflow, (
        "the pin rewrite hardcodes a bare 'vllm==v$VERSION' and drops every extra — "
        "the next vLLM release would silently undo the [audio] fix"
    )
    assert (
        'ARG VLLM_PIP_SPEC=\\"vllm${EXTRA}==v$VERSION\\"' in workflow
    ), "the pin rewrite no longer re-attaches ${EXTRA}"
    assert 'grep -F "vllm${EXTRA}==v$VERSION"' in workflow, "the post-rewrite guard no longer accounts for extras"

    pattern, group = _sed_substitution("EXTRA")
    cases = {
        'ARG VLLM_PIP_SPEC="vllm[audio]==v0.29.0"': "[audio]",
        'ARG VLLM_PIP_SPEC="vllm[audio,video]==v0.29.0"': "[audio,video]",
    }
    for line, expected in cases.items():
        match = pattern.search(line)
        assert match, f"extras not recognised in {line!r}"
        assert match.group(group) == expected, f"read {match.group(group)!r} instead of {expected!r} from {line!r}"

    # A bare pin yields an empty EXTRA, so the rewrite stays "vllm==v<version>".
    match = pattern.search('ARG VLLM_PIP_SPEC="vllm==v0.29.0"')
    assert match, "a pin without extras is no longer matched at all"
    assert (match.group(group) or "") == ""
