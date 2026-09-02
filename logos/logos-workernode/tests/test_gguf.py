from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

from logos_worker_node import gguf

# ---------------------------------------------------------------------------
# Quant type vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quant",
    [
        # File (LlamaFileType) quants
        "F16",
        "BF16",
        "Q4_0",
        "Q4_1",
        "Q8_0",
        "Q4_K_M",
        "Q4_K_S",
        "Q5_K_M",
        "IQ2_XXS",
        "IQ4_XS",
        "TQ1_0",
        # Tensor (GGML) base quants
        "Q4_K",
        "Q3_K",
        "I8",
        "F32",
        # Extended convention: tensor type + suffix
        "Q5_K_L",
        "Q2_K_S",
        "IQ3_M",
    ],
)
def test_is_valid_gguf_quant_type_accepts_known_names(quant: str) -> None:
    assert gguf.is_valid_gguf_quant_type(quant) is True


@pytest.mark.parametrize("quant", ["", "Q9_X", "Q4_K_", "quantum", "4_K", "Q4K_M", "QX_K_M"])
def test_is_valid_gguf_quant_type_rejects_unknown_names(quant: str) -> None:
    assert gguf.is_valid_gguf_quant_type(quant) is False


def test_is_valid_gguf_quant_type_strips_whitespace() -> None:
    assert gguf.is_valid_gguf_quant_type("  Q4_K_M  ") is True


def test_is_nonstandard_gguf_quant_type() -> None:
    assert gguf.is_nonstandard_gguf_quant_type("UD-Q4_K_XL") is True
    assert gguf.is_nonstandard_gguf_quant_type("Custom-Q8_0") is True
    # No dash → not the non-standard convention
    assert gguf.is_nonstandard_gguf_quant_type("Q4_K_M") is False
    # Dash but no recognizable trailing quant
    assert gguf.is_nonstandard_gguf_quant_type("foo-bar") is False


# ---------------------------------------------------------------------------
# Reference detection
# ---------------------------------------------------------------------------


def test_is_remote_gguf_ref() -> None:
    assert gguf.is_remote_gguf_ref("unsloth/Qwen3-8B-GGUF:Q4_K_M") is True
    assert gguf.is_remote_gguf_ref("bartowski/Llama-3.1-8B-Instruct-GGUF:UD-Q4_K_XL") is True
    # No colon
    assert gguf.is_remote_gguf_ref("unsloth/Qwen3-8B-GGUF") is False
    # Colon with an unknown quant
    assert gguf.is_remote_gguf_ref("unsloth/Qwen3-8B-GGUF:Q9_X") is False
    # repo/file.gguf is a file ref, not a remote ref
    assert gguf.is_remote_gguf_ref("unsloth/Qwen3-8B-GGUF/Qwen3-8B-00001-of-00002-Q4_K_M.gguf") is False
    assert gguf.is_remote_gguf_ref("") is False


def test_is_remote_gguf_ref_is_case_insensitive_in_quant() -> None:
    # The quant token's canonical form is uppercase; a lowercase reference is
    # recognized the same as its uppercase form.
    assert gguf.is_remote_gguf_ref("unsloth/Qwen3-8B-GGUF:q4_k_m") is True
    assert gguf.is_remote_gguf_ref("unsloth/Qwen3-8B-GGUF:Q4_K_M") is True
    # Unknown quant, in any case, is still rejected.
    assert gguf.is_remote_gguf_ref("unsloth/Qwen3-8B-GGUF:q9_x") is False


def test_is_gguf_file_ref() -> None:
    assert gguf.is_gguf_file_ref("/models/Qwen3-8B-Q4_K_M.gguf") is True
    assert gguf.is_gguf_file_ref("unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf") is True
    assert gguf.is_gguf_file_ref("unsloth/Qwen3-8B-GGUF") is False


def test_is_remote_gguf_file_ref() -> None:
    assert gguf.is_remote_gguf_file_ref("unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf") is True
    # A local path is a plain filesystem check, not a Hub reference.
    assert gguf.is_remote_gguf_file_ref("/models/Qwen3-8B-Q4_K_M.gguf") is False
    # Relative local paths are not Hub references either — repo_id_of() would
    # return "./models" and the worker would chase a Hub snapshot the file
    # will never come from.
    assert gguf.is_remote_gguf_file_ref("./models/model.gguf") is False
    assert gguf.is_remote_gguf_file_ref("../models/model.gguf") is False
    # A deeper path is not invertible to a repo id either.
    assert gguf.is_remote_gguf_file_ref("unsloth/Qwen3-8B-GGUF/quants/model.gguf") is False
    # No repository component (or not a file at all) → not remote.
    assert gguf.is_remote_gguf_file_ref("Qwen3-8B.gguf") is False
    assert gguf.is_remote_gguf_file_ref("unsloth/Qwen3-8B-GGUF") is False


def test_is_local_gguf_dir_ref() -> None:
    # The documented /path/to/dir:<quant_type> form — the quant is embedded
    # in the reference, so the directory name needs no -GGUF marker.
    assert gguf.is_local_gguf_dir_ref("/models/qwen-GGUF:Q4_K_M") is True
    assert gguf.is_local_gguf_dir_ref("/models/qwen:Q4_K_M") is True
    # Quant matching is case-insensitive, like the remote repo:quant form.
    assert gguf.is_local_gguf_dir_ref("/models/qwen-GGUF:q4_k_m") is True
    # A bare local directory counts only under the -GGUF naming convention …
    assert gguf.is_local_gguf_dir_ref("/models/qwen-GGUF") is True
    assert gguf.is_local_gguf_dir_ref("/models/qwen") is False
    # … and an unrecognizable quant token is no quant at all.
    assert gguf.is_local_gguf_dir_ref("/models/qwen:BOGUS") is False
    # Remote references are not local directories (and vice versa).
    assert gguf.is_local_gguf_dir_ref("unsloth/Qwen3-8B-GGUF:Q4_K_M") is False
    # Relative paths are not the documented absolute local form.
    assert gguf.is_local_gguf_dir_ref("./models/qwen-GGUF:Q4_K_M") is False
    assert gguf.is_local_gguf_dir_ref("../models/qwen-GGUF:Q4_K_M") is False


def test_local_dir_path_of() -> None:
    # The quant suffix is not part of the path: existence checks (capability
    # validation) target the directory alone, never "…:Q4_K_M".
    assert gguf.local_dir_path_of("/models/qwen-GGUF:Q4_K_M") == "/models/qwen-GGUF"
    assert gguf.local_dir_path_of("/models/qwen-GGUF") == "/models/qwen-GGUF"
    assert gguf.local_dir_path_of("unsloth/Qwen3-8B-GGUF:Q4_K_M") is None
    assert gguf.local_dir_path_of("/models/qwen") is None


def test_is_gguf_repo_name() -> None:
    assert gguf.is_gguf_repo_name("unsloth/Qwen3-8B-GGUF") is True
    assert gguf.is_gguf_repo_name("huihui_ai/gemma-3-4b-it-GGUF") is True
    assert gguf.is_gguf_repo_name("org/model_GGUF") is True  # underscore variant
    # The suffix must be the end of the name — "gguf" anywhere in the name is
    # not the convention and must not match (a false positive makes
    # resolve_gguf_spec fail a plain model with "pin a quant").
    assert gguf.is_gguf_repo_name("my-org/gguf-tools-model") is False
    assert gguf.is_gguf_repo_name("acme/GGUFactory-7B") is False
    assert gguf.is_gguf_repo_name("org/some_gguf_thing") is False
    assert gguf.is_gguf_repo_name("org/gguf") is False  # no dash/underscore suffix
    assert gguf.is_gguf_repo_name("Qwen/Qwen3-8B") is False
    # No org/ separator → not a repo id
    assert gguf.is_gguf_repo_name("Qwen3-8B-GGUF") is False


def test_hf_cache_dir_name_unifies_reference_forms() -> None:
    # Every reference form of the same repo maps to one HF cache directory —
    # the directory the startup prefetch fills — so the capability cache check
    # and the RAM cache never look in a directory the prefetch never wrote.
    bare = gguf.hf_cache_dir_name("unsloth/Qwen3-8B-GGUF")
    assert bare == "models--unsloth--Qwen3-8B-GGUF"
    assert gguf.hf_cache_dir_name("unsloth/Qwen3-8B-GGUF:Q4_K_M") == bare
    assert gguf.hf_cache_dir_name("unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf") == bare
    # Non-GGUF references are unchanged.
    assert gguf.hf_cache_dir_name("Qwen/Qwen3-8B") == "models--Qwen--Qwen3-8B"


def test_is_gguf_model_and_explicit_ref() -> None:
    remote = "unsloth/Qwen3-8B-GGUF:Q4_K_M"
    file_ref = "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf"
    bare = "unsloth/Qwen3-8B-GGUF"

    assert gguf.is_gguf_model(remote) is True
    assert gguf.is_gguf_model(file_ref) is True
    assert gguf.is_gguf_model(bare) is True
    assert gguf.is_gguf_model("Qwen/Qwen3-8B") is False

    assert gguf.is_explicit_gguf_ref(remote) is True
    assert gguf.is_explicit_gguf_ref(file_ref) is True
    assert gguf.is_explicit_gguf_ref(bare) is False
    assert gguf.is_explicit_gguf_ref("Qwen/Qwen3-8B") is False


def test_is_gguf_model_and_explicit_ref_include_local_dirs() -> None:
    # A local dir:quant reference carries its own quant — it is a GGUF model
    # AND an explicit reference: no listing (local or Hub) may resolve it.
    assert gguf.is_gguf_model("/models/qwen-GGUF:Q4_K_M") is True
    assert gguf.is_explicit_gguf_ref("/models/qwen-GGUF:Q4_K_M") is True
    # A bare local …-GGUF directory is explicit too (it serves its content
    # as-is), so tokenizer handling and the sharded-checkpoint bypass apply.
    assert gguf.is_gguf_model("/models/qwen-GGUF") is True
    assert gguf.is_explicit_gguf_ref("/models/qwen-GGUF") is True
    # A plain local directory without the marker is not a GGUF reference.
    assert gguf.is_gguf_model("/models/qwen") is False
    assert gguf.is_explicit_gguf_ref("/models/qwen") is False


def test_repo_id_of_all_reference_shapes() -> None:
    assert gguf.repo_id_of("unsloth/Qwen3-8B-GGUF") == "unsloth/Qwen3-8B-GGUF"
    assert gguf.repo_id_of("unsloth/Qwen3-8B-GGUF:Q4_K_M") == "unsloth/Qwen3-8B-GGUF"
    assert gguf.repo_id_of("unsloth/Qwen3-8B-GGUF/Qwen3-8B-00001-of-00002-Q4_K_M.gguf") == "unsloth/Qwen3-8B-GGUF"


# ---------------------------------------------------------------------------
# Quant extraction from file names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "quant"),
    [
        ("Qwen3-8B-Q4_K_M.gguf", "Q4_K_M"),
        ("Qwen3-8B-Q4_K_M-00001-of-00004.gguf", "Q4_K_M"),
        ("gpt2.Q8_0.gguf", "Q8_0"),
        # Non-standard (UD) quant: the standard trailing token is extracted;
        # it still resolves to the same file via the plugin's *-Q4_K_XL.gguf
        # pattern, and the exact name can be pinned via gguf_quant.
        ("Llama-3.1-8B-Instruct-UD-Q4_K_XL.gguf", "Q4_K_XL"),
        ("model.Q4_0-00002-of-00002.gguf", "Q4_0"),
        # Quant names are case-insensitive in file names; the canonical
        # uppercase form is what gets resolved (download patterns match both).
        ("model-q4_k_m.gguf", "Q4_K_M"),
        ("gpt2.q8_0.gguf", "Q8_0"),
        ("Qwen3-8B-q4_k_m-00001-of-00004.gguf", "Q4_K_M"),
        # Non-GGUF files
        ("tokenizer.gguf", None),
        ("README.md", None),
    ],
)
def test_quant_from_filename(filename: str, quant: str | None) -> None:
    assert gguf.quant_from_filename(filename) == quant


def test_quant_from_filename_dash_wins_over_dot() -> None:
    # Model names with dots (Qwen3.5) must not be mistaken for the
    # dot-separated quant naming.
    assert gguf.quant_from_filename("Qwen3.5-4B-Q4_K_M.gguf") == "Q4_K_M"


def test_candidate_quants_deduplicates_and_skips_mmproj() -> None:
    # ``candidate_quants`` reports (quant, total-bytes) pairs; the total is
    # the whole-quant footprint (shards summed), not a single file.
    filenames = [
        ("Qwen3-8B-Q4_K_M-00001-of-00002.gguf", 1024),
        ("Qwen3-8B-Q4_K_M-00002-of-00002.gguf", 1024),
        ("Qwen3-8B-Q4_K_S.gguf", 512),
        ("mmproj-Qwen3-8B-F16.gguf", 4096),
        ("tokenizer.gguf", 8),
    ]
    assert gguf.candidate_quants(filenames) == [("Q4_K_M", 2048), ("Q4_K_S", 512)]


def test_select_quant_preferred_wins() -> None:
    assert gguf.select_quant([("Q4_K_S", 1), ("Q4_K_M", 2)], preferred="Q4_K_S") == "Q4_K_S"


def test_select_quant_prefers_q4_k_m() -> None:
    # Q4_K_M is first in the preferred order regardless of listing order.
    assert gguf.select_quant([("Q8_0", 4), ("Q4_K_S", 3), ("Q4_K_M", 2)]) == "Q4_K_M"


def test_select_quant_fallback_smallest_file() -> None:
    # The fallback (no preferred quant present) orders the exotic quants by
    # ascending file size — not listing order, which the Hub tends to order
    # largest-first. The smallest loadable candidate wins, never the largest
    # variant merely because it happened to be listed first.
    assert gguf.select_quant([("IQ4_XS", 512)]) == "IQ4_XS"
    # Two exotic quants (neither in the preferred order): the 128 KiB one
    # beats the 2 MiB one, whatever order the listing gave them.
    assert gguf.select_quant([("TQ2_0", 2048), ("Q3_KS", 128)]) == "Q3_KS"
    assert gguf.select_quant([("Q3_KS", 128), ("TQ2_0", 2048)]) == "Q3_KS"
    # A repository whose only quants are float types still serves the only
    # available file — the fallback is a last resort, not a failure.
    assert gguf.select_quant([("BF16", 8192)]) == "BF16"
    assert gguf.select_quant([]) is None


# ---------------------------------------------------------------------------
# Local HF cache listing
# ---------------------------------------------------------------------------


def _write_gguf(hf_home: Path, model: str, filenames: list[str], sizes: list[int] | None = None) -> None:
    repo_dir = hf_home / "hub" / ("models--" + model.replace("/", "--"))
    snapshot = repo_dir / "snapshots" / "abc123"
    snapshot.mkdir(parents=True, exist_ok=True)
    # refs/main points at the active revision — the snapshot the listing walks.
    (repo_dir / "refs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "refs" / "main").write_text("abc123")
    for i, name in enumerate(filenames):
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\x00" * (sizes[i] if sizes else 1))


def test_list_cached_gguf_files_finds_cached_model(tmp_path: Path) -> None:
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "Qwen3-8B-Q4_K_M-00002-of-00002.gguf", "Qwen3-8B-Q4_K_S.gguf"],
    )
    files = gguf.list_cached_gguf_files(str(tmp_path), "unsloth/Qwen3-8B-GGUF")
    # (name, size) pairs, sorted by file name.
    assert files == [
        ("Qwen3-8B-Q4_K_M-00001-of-00002.gguf", 1),
        ("Qwen3-8B-Q4_K_M-00002-of-00002.gguf", 1),
        ("Qwen3-8B-Q4_K_S.gguf", 1),
    ]


def test_list_cached_gguf_files_ignores_zero_byte_and_non_gguf(tmp_path: Path) -> None:
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M.gguf", "empty.gguf", "tokenizer.gguf", "config.json"],
        sizes=[16, 0, 1, 1],
    )
    # Every non-empty .gguf is listed (including tokenizer.gguf — quant
    # extraction and the mmproj filter happen later in candidate_quants);
    # zero-byte downloads and non-GGUF files are not.
    files = gguf.list_cached_gguf_files(str(tmp_path), "unsloth/Qwen3-8B-GGUF")
    assert files == [("Qwen3-8B-Q4_K_M.gguf", 16), ("tokenizer.gguf", 1)]


def test_list_cached_gguf_files_none_when_not_cached(tmp_path: Path) -> None:
    assert gguf.list_cached_gguf_files(str(tmp_path), "unsloth/Qwen3-8B-GGUF") is None
    assert gguf.list_cached_gguf_files(str(tmp_path), "Qwen3-8B-GGUF") is None


def test_list_cached_gguf_files_empty_authoritative(tmp_path: Path) -> None:
    # Cached repo without GGUF weights → empty list, not None.
    _write_gguf(tmp_path, "org/some-model", ["config.json", "model.safetensors"])
    assert gguf.list_cached_gguf_files(str(tmp_path), "org/some-model") == []


def test_list_cached_model_weights_reports_both_formats(tmp_path: Path) -> None:
    # A mixed-format snapshot keeps the weight-format evidence: the GGUF
    # files AND the non-GGUF backbone weights that disqualify a plain name
    # from GGUF serving.
    _write_gguf(
        tmp_path,
        "org/mixed-model",
        ["model.safetensors", "model-Q4_K_M.gguf", "tokenizer.gguf", "config.json"],
    )
    gguf_files, non_gguf = gguf.list_cached_model_weights(str(tmp_path), "org/mixed-model")
    assert gguf_files == [("model-Q4_K_M.gguf", 1), ("tokenizer.gguf", 1)]
    assert non_gguf == ["model.safetensors"]


def test_list_cached_model_weights_gguf_only_has_no_backbone(tmp_path: Path) -> None:
    # A GGUF-only snapshot is authoritative about the ABSENCE of backbone
    # weights: the plain name may keep resolving to GGUF.
    _write_gguf(tmp_path, "org/gguf-only", ["Qwen3-8B-Q4_K_M.gguf", "tokenizer.gguf"])
    gguf_files, non_gguf = gguf.list_cached_model_weights(str(tmp_path), "org/gguf-only")
    assert [name for name, _ in gguf_files] == ["Qwen3-8B-Q4_K_M.gguf", "tokenizer.gguf"]
    assert non_gguf == []


def test_is_non_gguf_backbone_weight() -> None:
    # The backbone names a plain repository loads as a transformers model …
    assert gguf.is_non_gguf_backbone_weight("model.safetensors") is True
    assert gguf.is_non_gguf_backbone_weight("model-00001-of-00004.safetensors") is True
    assert gguf.is_non_gguf_backbone_weight("pytorch_model.bin") is True
    # … wherever the snapshot keeps them, in any case …
    assert gguf.is_non_gguf_backbone_weight("quants/model.bin") is True
    assert gguf.is_non_gguf_backbone_weight("MODEL.SAFETENSORS") is True
    # … but auxiliary weight files do not name the model — a GGUF-only repo
    # bundling one (an mmproj projector, a LoRA adapter) is still GGUF.
    assert gguf.is_non_gguf_backbone_weight("mmproj.safetensors") is False
    assert gguf.is_non_gguf_backbone_weight("adapter_model.safetensors") is False
    assert gguf.is_non_gguf_backbone_weight("tokenizer.gguf") is False
    assert gguf.is_non_gguf_backbone_weight("model-Q4_K_M.gguf") is False
    assert gguf.is_non_gguf_backbone_weight("config.json") is False


def test_list_cached_gguf_files_finds_nested_subdirectory_files(tmp_path: Path) -> None:
    # GGUF repositories often keep their weights in subdirectories (quants/,
    # …); the walk must reach them — bounded to the snapshot — and surface
    # snapshot-relative names.
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_S.gguf", "quants/Qwen3-8B-Q8_0.gguf", "quants/deep/Qwen3-8B-Q4_K_M.gguf"],
        sizes=[16, 32, 64],
    )
    files = gguf.list_cached_gguf_files(str(tmp_path), "unsloth/Qwen3-8B-GGUF")
    assert files == [
        ("Qwen3-8B-Q4_K_S.gguf", 16),
        ("quants/Qwen3-8B-Q8_0.gguf", 32),
        ("quants/deep/Qwen3-8B-Q4_K_M.gguf", 64),
    ]
    # The snapshot-relative name is harmless downstream: the quant helpers
    # basename their input, so a nested file still resolves its quant.
    assert [quant for quant, _ in gguf.candidate_quants(files)] == ["Q4_K_S", "Q8_0", "Q4_K_M"]


def test_list_cached_gguf_files_ignores_stale_older_snapshot(tmp_path: Path) -> None:
    # refs/main points at the active revision. An older cached snapshot that
    # still holds a formerly preferred quant must not leak into the listing —
    # otherwise select_quant would offer a quant the active branch removed,
    # and calibration/lane startup would build a repo:quant the current
    # repository cannot serve.
    repo_dir = tmp_path / "hub" / "models--unsloth--Qwen3-8B-GGUF"
    (repo_dir / "snapshots" / "old-rev").mkdir(parents=True)
    (repo_dir / "snapshots" / "new-rev").mkdir(parents=True)
    (repo_dir / "snapshots" / "old-rev" / "Qwen3-8B-Q4_K_M.gguf").write_bytes(b"\x00" * 16)
    (repo_dir / "snapshots" / "new-rev" / "Qwen3-8B-Q4_K_S.gguf").write_bytes(b"\x00" * 16)
    (repo_dir / "refs").mkdir()
    (repo_dir / "refs" / "main").write_text("new-rev")

    files = gguf.list_cached_gguf_files(str(tmp_path), "unsloth/Qwen3-8B-GGUF")
    # Only the active (new-rev) snapshot is listed; the stale Q4_K_M is gone.
    assert files == [("Qwen3-8B-Q4_K_S.gguf", 16)]
    # …so it is not a selectable candidate.
    assert gguf.select_quant(gguf.candidate_quants(files)) == "Q4_K_S"


def test_list_cached_gguf_files_unresolvable_ref_is_unavailable(tmp_path: Path) -> None:
    # Cached but no single active revision resolvable (multiple refs, no
    # refs/main) → the local listing is treated as unavailable (None), not
    # guessed across ambiguous revisions.
    repo_dir = tmp_path / "hub" / "models--unsloth--Qwen3-8B-GGUF"
    (repo_dir / "snapshots" / "rev-a").mkdir(parents=True)
    (repo_dir / "snapshots" / "rev-a" / "Qwen3-8B-Q4_K_M.gguf").write_bytes(b"\x00" * 16)
    (repo_dir / "refs").mkdir()
    (repo_dir / "refs" / "main").write_text("rev-a")
    (repo_dir / "refs" / "some-tag").write_text("rev-a")

    # A single refs/main resolves fine even with an extra snapshot present.
    assert gguf.list_cached_gguf_files(str(tmp_path), "unsloth/Qwen3-8B-GGUF") == [("Qwen3-8B-Q4_K_M.gguf", 16)]
    # Remove refs/main: now two refs remain → ambiguous → unavailable.
    (repo_dir / "refs" / "main").unlink()
    (repo_dir / "refs" / "other-tag").write_text("rev-a")
    assert gguf.list_cached_gguf_files(str(tmp_path), "unsloth/Qwen3-8B-GGUF") is None


# ---------------------------------------------------------------------------
# is_gguf_ref_cached — concrete quant/file presence in a (possibly partial) snapshot
# ---------------------------------------------------------------------------


def test_is_gguf_ref_cached_partial_snapshot_flags_other_quant(tmp_path: Path) -> None:
    # The regression case: the prefetch cached Q4_K_M, the capability now
    # pins Q8_0 of the SAME repository. The repository directory exists, but
    # the pinned quant does not — it must NOT count as cached.
    _write_gguf(tmp_path, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-Q4_K_M.gguf"])
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q8_0") is False
    # The cached quant satisfies its own reference (case-insensitively).
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q4_K_M") is True
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:q4_k_m") is True


def test_is_gguf_ref_cached_lowercase_cached_file_satisfies_quant(tmp_path: Path) -> None:
    # The download patterns match both cases, so a cache built from a
    # lowercase file name satisfies the canonical (uppercase) reference.
    _write_gguf(tmp_path, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-q4_k_m.gguf"])
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q4_K_M") is True


def test_is_gguf_ref_cached_repo_not_cached_is_unavailable(tmp_path: Path) -> None:
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q4_K_M") is None


def test_is_gguf_ref_cached_non_explicit_refs_are_not_checked(tmp_path: Path) -> None:
    # A bare repo picks its quant from whatever is cached, a local path is a
    # filesystem check — neither has a concrete snapshot target to verify.
    _write_gguf(tmp_path, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-Q4_K_M.gguf"])
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF") is None
    assert gguf.is_gguf_ref_cached(str(tmp_path), "/data/models/Qwen3-8B.gguf") is None
    assert gguf.is_gguf_ref_cached(str(tmp_path), "Qwen/Qwen3-8B") is None


def test_is_gguf_ref_cached_file_ref(tmp_path: Path) -> None:
    _write_gguf(tmp_path, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-Q4_K_M.gguf", "quants/Qwen3-8B-Q8_0.gguf"])
    # The named file is found — also when the repository keeps it in a
    # subdirectory (the reference names the file, the snapshot walk finds it) …
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf") is True
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q8_0.gguf") is True
    # … but a sibling file that was never cached is not.
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q5_K_M.gguf") is False


def test_is_gguf_ref_cached_sharded_file_ref_needs_whole_family(tmp_path: Path) -> None:
    # A reference to one shard of a multi-file quant must find the whole
    # -N-of-M family — the plugin's loader expands the first shard to it, so
    # a lone shard is not loadable and the prefetch (which downloads the
    # family) must still run.
    _write_gguf(tmp_path, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf"])
    ref = "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M-00001-of-00002.gguf"
    assert gguf.is_gguf_ref_cached(str(tmp_path), ref) is False
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "Qwen3-8B-Q4_K_M-00002-of-00002.gguf"],
    )
    assert gguf.is_gguf_ref_cached(str(tmp_path), ref) is True
    # Referring to the second shard gives the same answer.
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M-00002-of-00002.gguf") is True


def test_is_gguf_ref_cached_sharded_quant_needs_all_shards(tmp_path: Path) -> None:
    _write_gguf(tmp_path, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf"])
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q4_K_M") is False
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "Qwen3-8B-Q4_K_M-00002-of-00002.gguf"],
    )
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q4_K_M") is True


def test_is_gguf_ref_cached_sharded_file_ref_family_must_be_in_one_path(tmp_path: Path) -> None:
    # Shards of the same family split across directories — or duplicate
    # indices inflating a basename count — do not make the model loadable:
    # the loader reads the family from the one path it finds it in.
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "quants/Qwen3-8B-Q4_K_M-00001-of-00002.gguf"],
    )
    ref = "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M-00001-of-00002.gguf"
    assert gguf.is_gguf_ref_cached(str(tmp_path), ref) is False
    # A complete family in ONE directory satisfies the reference, even with
    # the stray shard of another directory left behind.
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "Qwen3-8B-Q4_K_M-00002-of-00002.gguf"],
    )
    assert gguf.is_gguf_ref_cached(str(tmp_path), ref) is True


def test_is_gguf_ref_cached_sharded_quant_family_must_be_in_one_path(tmp_path: Path) -> None:
    # Same completeness rule for a sharded QUANT: the indices must sit in a
    # single directory, not scattered across paths.
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "quants/Qwen3-8B-Q4_K_M-00002-of-00002.gguf"],
    )
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q4_K_M") is False
    _write_gguf(
        tmp_path,
        "unsloth/Qwen3-8B-GGUF",
        ["Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "Qwen3-8B-Q4_K_M-00002-of-00002.gguf"],
    )
    assert gguf.is_gguf_ref_cached(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q4_K_M") is True


def test_is_gguf_ref_cached_sharded_quant_families_do_not_complete_each_other(tmp_path: Path) -> None:
    model = "unsloth/Qwen3-8B-GGUF"
    # Different filename families of the same quant must not complete each
    # other: A-…-00001-of-00002 + B-…-00002-of-00002 in the same directory
    # hold indices {1,2}, but NEITHER family is loadable. Merging their
    # indices reported the partial cache complete and suppressed the
    # prefetch that repairs it.
    cross_family = tmp_path / "cross_family"
    _write_gguf(cross_family, model, ["A-Q4_K_M-00001-of-00002.gguf", "B-Q4_K_M-00002-of-00002.gguf"])
    assert gguf.is_gguf_ref_cached(str(cross_family), f"{model}:Q4_K_M") is False
    # The declared total is part of the family key too: one shard of a
    # 2-shard family plus one shard of a 3-shard family of the same base
    # name are still two incomplete models.
    cross_total = tmp_path / "cross_total"
    _write_gguf(cross_total, model, ["A-Q4_K_M-00001-of-00002.gguf", "A-Q4_K_M-00002-of-00003.gguf"])
    assert gguf.is_gguf_ref_cached(str(cross_total), f"{model}:Q4_K_M") is False
    # A single complete family stays available.
    complete = tmp_path / "complete"
    _write_gguf(complete, model, ["A-Q4_K_M-00001-of-00002.gguf", "A-Q4_K_M-00002-of-00002.gguf"])
    assert gguf.is_gguf_ref_cached(str(complete), f"{model}:Q4_K_M") is True


def test_is_gguf_ref_cached_local_dir_ref_checks_the_directory(tmp_path: Path) -> None:
    # A local dir:quant reference is a filesystem fact, not a Hub cache: the
    # check targets the directory WITHOUT the quant suffix (no path ever
    # ends in ":Q4_K_M"), and no hf_home listing is involved.
    local_dir = tmp_path / "qwen-GGUF"
    local_dir.mkdir()
    assert gguf.is_gguf_ref_cached(str(tmp_path), f"{local_dir}:Q4_K_M") is True
    assert gguf.is_gguf_ref_cached(str(tmp_path), str(local_dir)) is True
    assert gguf.is_gguf_ref_cached(str(tmp_path), f"{tmp_path / 'missing-GGUF'}:Q4_K_M") is False


# ---------------------------------------------------------------------------
# gguf_capability_target — the concrete reference a capability cache check proves
# ---------------------------------------------------------------------------


def test_gguf_capability_target_shapes(tmp_path: Path) -> None:
    _write_gguf(tmp_path, "unsloth/Qwen3-8B-GGUF", ["Qwen3-8B-Q4_K_M.gguf"])
    # Explicit references validate themselves …
    assert gguf.gguf_capability_target(str(tmp_path), "unsloth/Qwen3-8B-GGUF:Q8_0") == "unsloth/Qwen3-8B-GGUF:Q8_0"
    assert (
        gguf.gguf_capability_target(str(tmp_path), "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf")
        == "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf"
    )
    # … a bare repository its operator pin …
    assert gguf.gguf_capability_target(str(tmp_path), "unsloth/Qwen3-8B-GGUF", pinned_quant="Q8_0") == (
        "unsloth/Qwen3-8B-GGUF:Q8_0"
    )
    # … an invalid pin changes nothing the check can prove (directory check) …
    assert gguf.gguf_capability_target(str(tmp_path), "unsloth/Qwen3-8B-GGUF", pinned_quant="Q9_X") is None
    # … else the quant the spec resolver auto-selects from the cached listing.
    assert gguf.gguf_capability_target(str(tmp_path), "unsloth/Qwen3-8B-GGUF") == "unsloth/Qwen3-8B-GGUF:Q4_K_M"
    # Plain models and local paths are not a GGUF concern (directory check).
    assert gguf.gguf_capability_target(str(tmp_path), "Qwen/Qwen3-8B") is None
    assert gguf.gguf_capability_target(str(tmp_path), "/data/models/model.gguf") is None
    # An unresolvable listing proves nothing — the bare repo must stay missing.
    assert gguf.gguf_capability_target(str(tmp_path), "org/never-cached-GGUF") == "org/never-cached-GGUF"
    # A cached repo without GGUF files serves as a plain model (directory
    # check) … a cached repo holding only auxiliary files cannot resolve a
    # quant (stays missing).
    _write_gguf(tmp_path, "org/plain-GGUF", ["config.json"])
    assert gguf.gguf_capability_target(str(tmp_path), "org/plain-GGUF") is None
    _write_gguf(tmp_path, "org/aux-only-GGUF", ["tokenizer.gguf"])
    assert gguf.gguf_capability_target(str(tmp_path), "org/aux-only-GGUF") == "org/aux-only-GGUF"


def test_gguf_capability_target_local_dir_ref_is_itself() -> None:
    # A local dir:quant reference proves itself: the cache check is the
    # directory's existence, never a snapshot listing. A bare -GGUF local
    # directory must not fall into the bare-REPO branch (its path segment
    # ends in -GGUF, but that convention is about repo names, not paths).
    assert gguf.gguf_capability_target(None, "/models/qwen-GGUF:Q4_K_M") == "/models/qwen-GGUF:Q4_K_M"
    assert gguf.gguf_capability_target(None, "/models/qwen-GGUF") == "/models/qwen-GGUF"


# ---------------------------------------------------------------------------
# Download allow patterns
# ---------------------------------------------------------------------------


def test_download_allow_patterns_non_gguf_is_none() -> None:
    assert gguf.download_allow_patterns("Qwen/Qwen3-8B", "Q4_K_M") is None


def test_download_allow_patterns_file_ref() -> None:
    # The pattern is the repo file name — HF allow_patterns match on names.
    assert gguf.download_allow_patterns("unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf", "") == ["Qwen3-8B-Q4_K_M.gguf"]


def test_download_allow_patterns_sharded_file_ref_fetches_whole_family() -> None:
    # An explicit reference to ONE shard of a multi-file quant must download
    # every shard of the family — the lane loads the whole model, so a single
    # shard would leave it incomplete (fetched at startup, or failing offline).
    patterns = gguf.download_allow_patterns("unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M-00001-of-00002.gguf", "")
    assert patterns == ["*Qwen3-8B-Q4_K_M-*-of-*.gguf"]
    # Covers both shards of the family, in the repo root or a subdirectory …
    assert fnmatch.fnmatch("Qwen3-8B-Q4_K_M-00001-of-00002.gguf", patterns[0])
    assert fnmatch.fnmatch("Qwen3-8B-Q4_K_M-00002-of-00002.gguf", patterns[0])
    assert fnmatch.fnmatch("quants/Qwen3-8B-Q4_K_M-00002-of-00002.gguf", patterns[0])
    # … but nothing from a different quant or a single-file reference.
    assert not fnmatch.fnmatch("Qwen3-8B-Q4_K_S.gguf", patterns[0])
    assert not fnmatch.fnmatch("Qwen3-8B-Q4_K_M.gguf", patterns[0])


def test_download_allow_patterns_sharded_file_ref_quant_last() -> None:
    # The alternative layout where the quant follows the shard indices.
    patterns = gguf.download_allow_patterns("unsloth/Qwen3-8B-GGUF/Qwen3-8B-00001-of-00002-Q4_K_M.gguf", "")
    assert patterns == ["*Qwen3-8B-*-of-*-Q4_K_M.gguf"]
    assert fnmatch.fnmatch("Qwen3-8B-00001-of-00002-Q4_K_M.gguf", patterns[0])
    assert fnmatch.fnmatch("Qwen3-8B-00002-of-00002-Q4_K_M.gguf", patterns[0])


def test_download_allow_patterns_repo_without_quant_is_none() -> None:
    # Nothing to filter on yet — the caller falls back to a full download.
    assert gguf.download_allow_patterns("unsloth/Qwen3-8B-GGUF", "") is None


def test_download_allow_patterns_repo_with_quant() -> None:
    patterns = gguf.download_allow_patterns("unsloth/Qwen3-8B-GGUF", "Q4_K_M")
    assert patterns is not None
    # Covers both naming styles (Qwen3-8B-Q4_K_M.gguf / Qwen3-8B.Q4_K_M.gguf),
    # with and without a shard suffix, in upper and lower case — the same
    # pattern set the GGUF plugin's own download resolves to.
    assert "*-Q4_K_M.gguf" in patterns
    assert "*-Q4_K_M-*.gguf" in patterns
    assert "*.Q4_K_M.gguf" in patterns
    assert "*.q4_k_m.gguf" in patterns
    # Only the one quantization is downloaded.
    assert len(patterns) == 8
    assert all("q4_k_m" in p.lower() for p in patterns)


# ---------------------------------------------------------------------------
# Serve-spec resolution
# ---------------------------------------------------------------------------


def test_resolve_gguf_spec_none_for_plain_model() -> None:
    assert gguf.resolve_gguf_spec("Qwen/Qwen3-8B") is None
    assert gguf.resolve_gguf_spec("") is None


def test_resolve_gguf_spec_remote_ref_passthrough() -> None:
    spec = gguf.resolve_gguf_spec("unsloth/Qwen3-8B-GGUF:Q4_K_M")
    assert spec is not None
    assert spec.serve_ref == "unsloth/Qwen3-8B-GGUF:Q4_K_M"
    assert spec.quant == "Q4_K_M"
    assert spec.tokenizer is None


def test_resolve_gguf_spec_remote_ref_lowercase_canonicalized() -> None:
    # A lowercase repo:quant reference is served under its canonical uppercase
    # quant, so vllm/the plugin receive the same reference as the uppercase
    # form (the download patterns already match both cases).
    spec = gguf.resolve_gguf_spec("unsloth/Qwen3-8B-GGUF:q4_k_m")
    assert spec is not None
    assert spec.serve_ref == "unsloth/Qwen3-8B-GGUF:Q4_K_M"
    assert spec.quant == "Q4_K_M"


def test_resolve_gguf_spec_remote_ref_with_tokenizer() -> None:
    spec = gguf.resolve_gguf_spec("unsloth/Qwen3-8B-GGUF:Q4_K_M", gguf_tokenizer="Qwen/Qwen3-8B")
    assert spec is not None
    assert spec.tokenizer == "Qwen/Qwen3-8B"


def test_resolve_gguf_spec_file_ref_passthrough() -> None:
    ref = "unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf"
    spec = gguf.resolve_gguf_spec(ref)
    assert spec is not None
    assert spec.serve_ref == ref
    assert spec.quant is None


def test_resolve_gguf_spec_local_dir_quant_ref() -> None:
    # Regression: the documented local form /path/model-GGUF:Q4_K_M was read
    # as a bare -GGUF repository — resolution chased a Hub listing for a
    # path and failed with "no quant discovered". The quant comes from the
    # reference itself: no listing (gguf_file_names=None) is consulted, and
    # the serve reference keeps the dir:quant form the plugin parses.
    spec = gguf.resolve_gguf_spec(
        "/models/qwen-GGUF:q4_k_m",
        gguf_tokenizer="Qwen/Qwen3-8B",
        gguf_file_names=None,
    )
    assert spec is not None
    assert spec.serve_ref == "/models/qwen-GGUF:Q4_K_M"
    assert spec.quant == "Q4_K_M"
    assert spec.tokenizer == "Qwen/Qwen3-8B"


def test_resolve_gguf_spec_bare_local_gguf_dir() -> None:
    # A bare local …-GGUF directory is an explicit reference that serves its
    # content as-is — no quant to discover, nothing to list.
    spec = gguf.resolve_gguf_spec("/models/qwen-GGUF")
    assert spec is not None
    assert spec.serve_ref == "/models/qwen-GGUF"
    assert spec.quant is None


def test_resolve_gguf_spec_bare_repo_auto_quant() -> None:
    spec = gguf.resolve_gguf_spec(
        "unsloth/Qwen3-8B-GGUF",
        gguf_file_names=[("Qwen3-8B-Q4_K_S.gguf", 512), ("Qwen3-8B-Q4_K_M-00001-of-00002.gguf", 1024)],
    )
    assert spec is not None
    assert spec.serve_ref == "unsloth/Qwen3-8B-GGUF:Q4_K_M"
    assert spec.quant == "Q4_K_M"


def test_resolve_gguf_spec_bare_repo_lowercase_filename() -> None:
    # Regression: a bare repo whose weights are a lowercase-quant file
    # (model-q4_k_m.gguf) must still resolve to the canonical uppercase quant.
    # The quant tail was matched case-sensitively, so the file came back as no
    # candidate and the lane failed at spawn time with a quant error.
    spec = gguf.resolve_gguf_spec(
        "unsloth/Qwen3-8B-GGUF",
        gguf_file_names=[("model-q4_k_m.gguf", 1024)],
    )
    assert spec is not None
    assert spec.serve_ref == "unsloth/Qwen3-8B-GGUF:Q4_K_M"
    assert spec.quant == "Q4_K_M"


def test_resolve_gguf_spec_bare_repo_operator_pin_wins() -> None:
    spec = gguf.resolve_gguf_spec(
        "unsloth/Qwen3-8B-GGUF",
        gguf_quant="q4_k_s",
        gguf_file_names=[("Qwen3-8B-Q4_K_M.gguf", 1024), ("Qwen3-8B-Q4_K_S.gguf", 512)],
    )
    assert spec is not None
    assert spec.serve_ref == "unsloth/Qwen3-8B-GGUF:Q4_K_S"


def test_resolve_gguf_spec_bare_repo_pin_without_listing() -> None:
    # Listing unavailable (None) — an operator pin still resolves.
    spec = gguf.resolve_gguf_spec("unsloth/Qwen3-8B-GGUF", gguf_quant="Q4_K_M")
    assert spec is not None
    assert spec.serve_ref == "unsloth/Qwen3-8B-GGUF:Q4_K_M"


def test_resolve_gguf_spec_bare_repo_unresolvable_raises() -> None:
    # No listing, no pin → serving a bare GGUF repo is impossible; the lane
    # must fail with an actionable message, not a vLLM cryptic error.
    with pytest.raises(ValueError, match="gguf_quant"):
        gguf.resolve_gguf_spec("unsloth/Qwen3-8B-GGUF")


def test_resolve_gguf_spec_cached_listing_without_gguf_disproves_plain_name() -> None:
    # A plain name plus an authoritative cached listing without GGUF weights
    # is not a GGUF model — serve it as a regular model.
    assert gguf.resolve_gguf_spec("org/some-model", gguf_file_names=[]) is None


def test_resolve_gguf_spec_authoritative_empty_listing_is_not_gguf() -> None:
    # An authoritative listing — a list, from the local cache OR the Hub —
    # that contains no GGUF files is proof the repo holds no GGUF weights,
    # even when its name follows the ``…-GGUF`` convention. The name alone
    # no longer gets the benefit of the doubt once the listing actually
    # resolved; the lane is served as a (non-GGUF) model. Only an
    # *unavailable* listing (None) keeps the name's benefit of the doubt.
    assert gguf.resolve_gguf_spec("unsloth/Qwen3-8B-GGUF", gguf_file_names=[]) is None
    # An unavailable listing (None) still raises for a nameless-quant repo.
    with pytest.raises(ValueError, match="gguf_quant"):
        gguf.resolve_gguf_spec("unsloth/Qwen3-8B-GGUF")


def test_resolve_gguf_spec_plain_name_with_gguf_cache_is_gguf() -> None:
    # Name doesn't follow the convention, but the cached listing proves the
    # repo only contains GGUF weights.
    spec = gguf.resolve_gguf_spec(
        "org/some-quantized-model",
        gguf_file_names=[("some-model-Q4_K_M.gguf", 1024)],
        non_gguf_weight_names=[],
    )
    assert spec is not None
    assert spec.serve_ref == "org/some-quantized-model:Q4_K_M"


def test_resolve_gguf_spec_mixed_format_plain_repo_is_not_gguf() -> None:
    # Regression: a plain-named repository whose listing holds BOTH backbone
    # weights (model.safetensors) and GGUF files used to be forced onto the
    # GGUF path — the safetensors backbone the name refers to was dropped.
    # The backbone wins: the model is served as a plain model.
    assert (
        gguf.resolve_gguf_spec(
            "org/some-model",
            gguf_file_names=[("some-model-Q4_K_M.gguf", 1024)],
            non_gguf_weight_names=["model.safetensors"],
        )
        is None
    )
    # The disqualifier is the BACKBONE, not any auxiliary weight file: a
    # GGUF-only repo bundling an mmproj projector is still GGUF.
    spec = gguf.resolve_gguf_spec(
        "org/some-model",
        gguf_file_names=[("some-model-Q4_K_M.gguf", 1024)],
        non_gguf_weight_names=["mmproj.safetensors"],
    )
    assert spec is not None
    assert spec.serve_ref == "org/some-model:Q4_K_M"


def test_resolve_gguf_spec_mixed_format_gguf_named_repo_stays_gguf() -> None:
    # A …-GGUF named repository is the operator's explicit GGUF choice: even
    # a mixed-format listing serves the GGUF quant, not the backbone.
    spec = gguf.resolve_gguf_spec(
        "org/some-model-GGUF",
        gguf_file_names=[("some-model-Q4_K_M.gguf", 1024)],
        non_gguf_weight_names=["model.safetensors"],
    )
    assert spec is not None
    assert spec.serve_ref == "org/some-model-GGUF:Q4_K_M"


def test_resolve_gguf_spec_unknown_weight_evidence_keeps_old_behaviour() -> None:
    # non_gguf_weight_names=None (no listing evidence, e.g. a Hub listing for
    # a -GGUF name) does not disprove a plain name with GGUF files.
    spec = gguf.resolve_gguf_spec(
        "org/some-model",
        gguf_file_names=[("some-model-Q4_K_M.gguf", 1024)],
    )
    assert spec is not None
    assert spec.serve_ref == "org/some-model:Q4_K_M"


def test_resolve_gguf_spec_auxiliary_only_listing_is_not_gguf() -> None:
    # Second-stage detection must rest on quant-bearing backbone files, not on
    # any non-empty listing: a plain repository whose cached .gguf artifacts
    # are only auxiliary (a tokenizer, an mmproj projector) is an ordinary
    # model, not a GGUF one. Counting the listing as proof of GGUF weights
    # drove select_quant([]) to None and made resolution raise.
    assert (
        gguf.resolve_gguf_spec(
            "org/some-model",
            gguf_file_names=[("tokenizer.gguf", 1), ("model.safetensors", 1)],
        )
        is None
    )
    # An mmproj projector is a different model part, not the backbone —
    # excluded the same way even though its name carries a quant.
    assert gguf.resolve_gguf_spec("org/some-model", gguf_file_names=[("mmproj-Q4_K_M.gguf", 1)]) is None
