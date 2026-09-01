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
    repo_dir = hf_home / "hub" / gguf.hf_cache_dir_name(model)
    snapshot = repo_dir / "snapshots" / "abc123"
    snapshot.mkdir(parents=True, exist_ok=True)
    # refs/main points at the active revision — the snapshot the listing walks.
    (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs" / "main").write_text("abc123")
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


def test_validate_capabilities_partial_snapshot_reports_missing_quant(tmp_path: Path, monkeypatch) -> None:
    # The partial-cache regression: Hugging Face snapshots can be partial —
    # the prefetch cached Q4_K_M of the repository, and the capability now
    # pins Q8_0 of the SAME repo. The repository directory exists, so the
    # directory-only check excluded the model from `missing` and the prefetch
    # never downloaded Q8_0. The concrete quant must be resolved and checked
    # inside the active snapshot instead.
    monkeypatch.delenv("HF_HOME", raising=False)
    cache_root = tmp_path / "root"
    (cache_root / "models").mkdir(parents=True)
    manager = LaneManager(
        OllamaConfig(models_path=str(cache_root / "models")),
        lane_port_start=16041,
        lane_port_end=16050,
    )
    _write_cached(cache_root / "models" / ".hf_cache", "org/model-GGUF", ["model-GGUF-Q4_K_M.gguf"])

    # A quant the snapshot does not hold is missing (prefetch triggered) …
    assert manager.validate_capabilities(["org/model-GGUF:Q8_0"]) == ["org/model-GGUF:Q8_0"]
    # … while the fully cached quant stays excluded from missing.
    assert manager.validate_capabilities(["org/model-GGUF:Q4_K_M"]) == []
    # An explicit file reference is checked the same way.
    assert manager.validate_capabilities(["org/model-GGUF/model-GGUF-Q5_K_M.gguf"]) == [
        "org/model-GGUF/model-GGUF-Q5_K_M.gguf"
    ]
    assert manager.validate_capabilities(["org/model-GGUF/model-GGUF-Q4_K_M.gguf"]) == []
    # A reference to a repository that is not cached at all is missing too.
    assert manager.validate_capabilities(["org/other-GGUF:Q4_K_M"]) == ["org/other-GGUF:Q4_K_M"]
    # A bare repository selects its quant from whatever the cache holds, so
    # the repository directory still satisfies it (unchanged behaviour).
    assert manager.validate_capabilities(["org/model-GGUF"]) == []


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


# ---------------------------------------------------------------------------
# spawn_vllm — the child receives the resolved HF cache root
# ---------------------------------------------------------------------------


def test_spawn_vllm_passes_resolved_default_hf_home(tmp_path: Path, monkeypatch) -> None:
    # With hf_home and HF_HOME unset, spawn_vllm must still point the child at
    # the resolved default cache root — the same root
    # _resolve_gguf_calibration_spec resolved the weights from — otherwise vLLM
    # misses locally-cached GGUF weights during offline calibration.
    import subprocess

    from logos_worker_node import calibration

    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.setenv("LOGOS_WORKER_CACHE_ROOT", str(tmp_path))

    captured = {}

    class _FakePopen:
        pid = 4242

        def __init__(self, cmd, env=None, **kwargs):  # noqa: ARG002
            captured["env"] = env

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    log_path = tmp_path / "logs" / "probe.log"

    # Unset hf_home / HF_HOME → the resolved default root reaches the child.
    calibration.spawn_vllm({"model": "org/plain-llm"}, "vllm", "127.0.0.1", 12999, log_path, "4G", hf_home=None)
    assert captured["env"]["HF_HOME"] == calibration._default_hf_home()

    # An explicit hf_home (tmpfs RAM cache) still wins over the default.
    captured.clear()
    ram = tmp_path / "ram"
    calibration.spawn_vllm({"model": "org/plain-llm"}, "vllm", "127.0.0.1", 12999, log_path, "4G", hf_home=str(ram))
    assert captured["env"]["HF_HOME"] == str(ram)
