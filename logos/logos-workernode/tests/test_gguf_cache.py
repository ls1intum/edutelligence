"""Regression tests for the GGUF cache-handling fixes.

Covers three retained issues: capability validation must check the ``.hf_cache``
directory the prefetch populates, the serving/calibration GGUF paths must respect
an inherited ``HF_HOME``, and an authoritative empty local listing must stay
authoritative (no HuggingFace Hub fallback) so locally cached models work
offline and redundant boot downloads stop.
"""

from __future__ import annotations

from pathlib import Path

from logos_worker_node import gguf
from logos_worker_node.calibration import _resolve_gguf_calibration_spec
from logos_worker_node.lane_manager import LaneManager
from logos_worker_node.models import OllamaConfig


def _write_cached(hf_home: Path, model: str, files: list[str] | None = None) -> None:
    """Create a snapshot dir under *hf_home* holding *files* (names only)."""
    snapshot = hf_home / "hub" / gguf.hf_cache_dir_name(model) / "snapshots" / "abc123"
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in files or []:
        (snapshot / name).write_bytes(b"\x00")


# ---------------------------------------------------------------------------
# effective_hf_home — respect the inherited HF_HOME
# ---------------------------------------------------------------------------


def test_effective_hf_home_precedence(monkeypatch) -> None:
    monkeypatch.setenv("HF_HOME", "/inherited/hf")
    # An explicit root (RAM cache / operator override) wins over everything.
    assert gguf.effective_hf_home("/explicit", "/default") == "/explicit"
    # With no explicit root, the inherited HF_HOME wins over the default.
    assert gguf.effective_hf_home(None, "/default") == "/inherited/hf"
    # A blank explicit value is treated as unset.
    assert gguf.effective_hf_home("   ", "/default") == "/inherited/hf"
    monkeypatch.delenv("HF_HOME")
    # Nothing explicit or inherited -> the resolved default.
    assert gguf.effective_hf_home(None, "/default") == "/default"
    assert gguf.effective_hf_home(None, "") == ""


# ---------------------------------------------------------------------------
# needs_hub_listing — an authoritative empty local listing stays local
# ---------------------------------------------------------------------------


def test_needs_hub_listing_only_absent_triggers_hub() -> None:
    # Absent listing for a convention-named repo -> fetch from the Hub.
    assert gguf.needs_hub_listing(None, "unsloth/Qwen3-8B-GGUF") is True
    # An authoritative EMPTY local listing is proof there are no GGUF weights —
    # it must not trigger a Hub fallback.
    assert gguf.needs_hub_listing([], "unsloth/Qwen3-8B-GGUF") is False
    # A non-empty local listing is authoritative too.
    assert gguf.needs_hub_listing([("model.gguf", 1)], "unsloth/Qwen3-8B-GGUF") is False
    # A plain (non-GGUF-named) repo never triggers a Hub fetch from here.
    assert gguf.needs_hub_listing(None, "org/plain-model") is False
    assert gguf.needs_hub_listing([], "org/plain-model") is False


# ---------------------------------------------------------------------------
# validate_capabilities — check the .hf_cache dir prefetch populates
# ---------------------------------------------------------------------------


def test_validate_capabilities_checks_hf_cache_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HF_HOME", raising=False)
    model = "org/some-model"

    # The directory the startup prefetch populates (.hf_cache) satisfies it.
    cache_root = tmp_path / "with_hf_cache"
    (cache_root / "models").mkdir(parents=True)
    manager = LaneManager(
        OllamaConfig(models_path=str(cache_root / "models")),
        lane_port_start=16001,
        lane_port_end=16010,
    )
    _write_cached(cache_root / "models" / ".hf_cache", model)
    assert manager.validate_capabilities([model]) == []

    # The old, wrong .hf dir alone must NOT satisfy validation — it is not
    # where the prefetch writes, so a prefetched model would be flagged missing.
    stale_root = tmp_path / "with_hf_only"
    (stale_root / "models").mkdir(parents=True)
    stale = LaneManager(
        OllamaConfig(models_path=str(stale_root / "models")),
        lane_port_start=16021,
        lane_port_end=16030,
    )
    (stale_root / "models" / ".hf" / "hub" / gguf.hf_cache_dir_name(model)).mkdir(parents=True)
    assert stale.validate_capabilities([model]) == [model]


# ---------------------------------------------------------------------------
# calibration resolver — inherited HF_HOME + authoritative empty listing
# ---------------------------------------------------------------------------


def test_calibration_spec_respects_inherited_hf_home(tmp_path: Path, monkeypatch) -> None:
    # A bare GGUF repo is cached under the inherited HF_HOME; the resolver must
    # find it there instead of falling back to the Hub.
    monkeypatch.delenv("HF_HOME", raising=False)
    hf_home = tmp_path / "hf"
    _write_cached(hf_home, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-Q4_K_M.gguf"])
    monkeypatch.setenv("HF_HOME", str(hf_home))

    hub_calls: list[str] = []
    monkeypatch.setattr(
        "logos_worker_node.calibration.fetch_repo_gguf_files",
        lambda repo: hub_calls.append(repo) or (("Qwen3-8B-Q4_K_M.gguf", 1),),
    )

    spec = _resolve_gguf_calibration_spec({"model": "unsloth/Qwen3-8B-GGUF"}, None)
    assert spec is not None
    assert spec.serve_ref == "unsloth/Qwen3-8B-GGUF:Q4_K_M"
    assert hub_calls == []  # resolved locally, no Hub fallback


def test_calibration_spec_empty_listing_no_hub(tmp_path: Path, monkeypatch) -> None:
    # An authoritative empty local listing (repo cached, no GGUF weights) must
    # stay authoritative: no Hub fallback, and the model is not treated as GGUF.
    monkeypatch.delenv("HF_HOME", raising=False)
    hf_home = tmp_path / "hf"
    _write_cached(hf_home, "unsloth/Qwen3-8B-GGUF", ["config.json"])  # no .gguf
    monkeypatch.setenv("HF_HOME", str(hf_home))

    hub_calls: list[str] = []
    monkeypatch.setattr(
        "logos_worker_node.calibration.fetch_repo_gguf_files",
        lambda repo: hub_calls.append(repo) or (("Qwen3-8B-Q4_K_M.gguf", 1),),
    )

    spec = _resolve_gguf_calibration_spec({"model": "unsloth/Qwen3-8B-GGUF"}, None)
    assert spec is None  # the empty listing disproves GGUF
    assert hub_calls == []  # no redundant Hub download
