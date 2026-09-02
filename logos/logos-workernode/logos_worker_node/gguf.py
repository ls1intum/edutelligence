"""GGUF model detection and serve-target resolution for vLLM lanes.

GGUF serving in vLLM is provided by the out-of-tree ``vllm-gguf-plugin``
(vLLM moved GGUF quantization out of the tree; the worker image installs
the plugin next to vLLM). The plugin understands four model references:

- ``<repo_id>:<quant_type>``        — remote, quant picked by name (e.g. ``unsloth/Qwen3-8B-GGUF:Q4_K_M``)
- ``<repo_id>/<filename>.gguf``     — remote, explicit file
- ``/path/to/model.gguf``           — local file
- ``/path/to/dir:<quant_type>``     — local directory, quant picked by name

Multi-file GGUF models (``…-Q4_K_M-00001-of-00004.gguf``) are read
directly by the plugin's loader, which expands the first shard to the full
``-N-of-M`` set. No merge step is required: the ``gguf-split`` tool that
the old in-tree vLLM loader pointed operators at became unnecessary when
GGUF support moved to the plugin.

This module is the worker-side half of that: it auto-detects GGUF models
from the lane's model name and the model's file listing (local HF cache
first, HuggingFace Hub as fallback) and resolves the reference the lane
must actually be served with — plus the optional tokenizer (config
source) and the served model name, so a lane registered as
``unsloth/Qwen3-8B-GGUF`` keeps answering under that exact name even
though vLLM loads ``unsloth/Qwen3-8B-GGUF:Q4_K_M``.
"""

from __future__ import annotations

import itertools
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quant type vocabulary
#
# Mirrors the validation in vllm-gguf-plugin (gguf_utils.is_valid_gguf_quant_type
# and is_nonstandard_gguf_quant_type) so the worker and the plugin accept the
# same quant names. Kept self-contained — the gguf package is a dependency of
# the plugin, not of this worker.
# ---------------------------------------------------------------------------

# File (LlamaFileType, MOSTLY_*) quant types — what appears in GGUF file names.
_FILE_QUANT_TYPES: frozenset[str] = frozenset(
    {
        "F16",
        "Q4_0",
        "Q4_1",
        "Q8_0",
        "Q5_0",
        "Q5_1",
        "Q2_K",
        "Q3_K_S",
        "Q3_K_M",
        "Q3_K_L",
        "Q4_K_S",
        "Q4_K_M",
        "Q5_K_S",
        "Q5_K_M",
        "Q6_K",
        "IQ2_XXS",
        "IQ2_XS",
        "Q2_K_S",
        "IQ3_XS",
        "IQ3_XXS",
        "IQ1_S",
        "IQ4_NL",
        "IQ3_S",
        "IQ3_M",
        "IQ2_S",
        "IQ2_M",
        "IQ4_XS",
        "IQ1_M",
        "BF16",
        "TQ1_0",
        "TQ2_0",
    }
)

# GGML tensor quant types (GGMLQuantizationType) — base types such as Q4_K
# that file types extend with suffixes (Q4_K_M).
_TENSOR_QUANT_TYPES: frozenset[str] = frozenset(
    {
        "F32",
        "F16",
        "Q4_0",
        "Q4_1",
        "Q5_0",
        "Q5_1",
        "Q8_0",
        "Q8_1",
        "Q2_K",
        "Q3_K",
        "Q4_K",
        "Q5_K",
        "Q6_K",
        "Q8_K",
        "IQ2_XXS",
        "IQ2_XS",
        "IQ3_XXS",
        "IQ1_S",
        "IQ4_NL",
        "IQ3_S",
        "IQ2_S",
        "IQ4_XS",
        "I8",
        "I16",
        "I32",
        "I64",
        "F64",
        "IQ1_M",
        "BF16",
        "TQ1_0",
        "TQ2_0",
    }
)

# Extended naming conventions: a file type may carry one of these suffixes on
# top of a tensor type (Q4_K_M = Q4_K + _M).
_QUANT_SUFFIXES: tuple[str, ...] = ("_M", "_S", "_L", "_XL", "_XS", "_XXS")

# Auto-selection order for a bare GGUF repository with no operator preference.
# Q4_K_M first — the de-facto standard quality/size point every major GGUF
# publisher ships; the remainder is a deterministic fallback order that
# prefers common, well-supported quantizations over exotic ones.
_PREFERRED_QUANTS: tuple[str, ...] = (
    "Q4_K_M",
    "Q4_K_S",
    "Q5_K_M",
    "Q5_K_S",
    "Q4_0",
    "Q5_0",
    "Q8_0",
    "Q6_K",
    "Q3_K_M",
    "Q3_K_L",
    "Q2_K",
    "IQ4_XS",
    "IQ4_NL",
    "IQ3_XXS",
    "IQ3_XS",
    "IQ2_XXS",
    "IQ2_XS",
    "IQ1_S",
    "IQ1_M",
    "BF16",
    "F16",
    "F32",
)

# repo:quant — same shape the plugin's is_remote_gguf accepts:
# org/name (dots allowed) plus a colon and a quant token.
_REMOTE_GGUF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9][a-zA-Z0-9._-]*:[A-Za-z0-9_+-]+$")

# repo/file.gguf — the same two org/name segments as above plus a file name
# without path separators. Local paths (/abs, ./, ../) are filesystem checks,
# not Hub references, and deeper repo paths cannot be inverted to a repo id —
# classifying either as remote would chase a Hub snapshot the file will never
# come from.
_REMOTE_GGUF_FILE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9][a-zA-Z0-9._-]*/[^/]+\.gguf$")

# Multi-file shard suffix: …-Q4_K_M-00001-of-00004.gguf
_SHARD_SUFFIX_RE = re.compile(r"-\d+-of-\d+$")

# Multi-file shard indices anywhere in the name (the suffix form above only
# matches the trailing …-00001-of-00004, so this also covers the
# …-00001-of-00002-Q4_K_M.gguf layout where the quant comes last).
_SHARD_INDEX_RE = re.compile(r"-\d+-of-\d+")


def _shard_marker_parts(marker: str) -> tuple[int, int]:
    """(index, total) of a ``-<index>-of-<total>`` shard marker."""
    index, total = marker.split("-of-", 1)
    return int(index.lstrip("-")), int(total)


# Non-GGUF backbone weight file name: the transformers-style weights a plain
# repository name refers to (model.safetensors, model-00001-of-00004.bin,
# pytorch_model.bin, …). Anchored on the backbone base name on purpose —
# auxiliary weight files (mmproj projectors, LoRA adapter_model.safetensors)
# do not name the model, so a GGUF-only repository bundling one is still
# GGUF, and only the backbone disqualifies a plain name from GGUF serving.
_NON_GGUF_WEIGHT_RE = re.compile(r"^(pytorch_)?model(-\d+-of-\d+)?\.(safetensors|bin)$")


def is_non_gguf_backbone_weight(filename: str) -> bool:
    """Whether *filename* names non-GGUF backbone weights.

    ``model.safetensors``, ``model-00001-of-00004.safetensors``,
    ``pytorch_model.bin`` — the weights a plain (non-``…-GGUF``) repository
    name loads as a transformers model. A repository shipping them also
    shipping GGUF files is mixed-format: the plain name refers to the
    backbone, and the GGUF files are an additional format, not the model.
    """
    name = (filename or "").rsplit("/", 1)[-1].lower()
    return bool(_NON_GGUF_WEIGHT_RE.fullmatch(name))


def is_valid_gguf_quant_type(quant_type: str) -> bool:
    """Whether *quant_type* is a known GGUF quantization name.

    Accepts file types (``Q4_K_M``, ``BF16``), tensor types (``Q4_K``) and the
    extended ``<tensor><suffix>`` convention.
    """
    qt = (quant_type or "").strip()
    if not qt:
        return False
    if qt in _FILE_QUANT_TYPES or qt in _TENSOR_QUANT_TYPES:
        return True
    for suffix in _QUANT_SUFFIXES:
        if qt.endswith(suffix) and qt[: -len(suffix)] in _TENSOR_QUANT_TYPES:
            return True
    return False


def is_nonstandard_gguf_quant_type(quant_type: str) -> bool:
    """Whether a non-standard quant name embeds a known GGML type.

    Dash-prefixed custom quants such as ``UD-Q4_K_XL`` or ``Custom-Q8_0`` are
    accepted when their trailing segment is a valid quant type (the plugin
    logs a warning and validates the file at download time).
    """
    qt = (quant_type or "").strip()
    if "-" not in qt:
        return False
    remainder = qt.rsplit("-", 1)[1]
    return is_valid_gguf_quant_type(remainder)


def is_remote_gguf_ref(model: str) -> bool:
    """Whether *model* is a ``<repo_id>:<quant_type>`` GGUF reference.

    The quant token is matched case-insensitively (the canonical form is
    uppercase), so ``org/model-GGUF:q4_k_m`` is recognized the same as
    ``org/model-GGUF:Q4_K_M``.
    """
    model = (model or "").strip()
    if not _REMOTE_GGUF_RE.fullmatch(model):
        return False
    quant_type = model.rsplit(":", 1)[1].upper()
    return is_valid_gguf_quant_type(quant_type) or is_nonstandard_gguf_quant_type(quant_type)


def is_gguf_file_ref(model: str) -> bool:
    """Whether *model* names a GGUF file (local path or ``repo/file.gguf``)."""
    return (model or "").strip().lower().endswith(".gguf")


def is_remote_gguf_file_ref(model: str) -> bool:
    """Whether *model* is a ``namespace/repository/file.gguf`` reference.

    Only the strict two-segment repository shape counts: local paths
    (``/abs/…``, ``./…``, ``../…``) and deeper repo paths are not Hub
    references, so they must not enter snapshot validation or Hub downloads.
    """
    model = (model or "").strip()
    return bool(_REMOTE_GGUF_FILE_RE.fullmatch(model))


def is_local_gguf_dir_ref(model: str) -> bool:
    """Whether *model* is a local-directory GGUF reference.

    The documented ``/path/to/dir:<quant_type>`` form — a local directory
    whose quant is embedded in the reference — and a bare local
    ``…-GGUF`` directory, whose name carries the repo naming convention.
    Local paths are never Hub references: their presence is a filesystem
    fact and their quant evidence lives in the directory itself, so no
    listing (local or Hub) is needed to resolve them.
    """
    model = (model or "").strip()
    if not model.startswith("/"):
        return False
    if ":" in model:
        quant = model.rsplit(":", 1)[1].upper()
        return is_valid_gguf_quant_type(quant) or is_nonstandard_gguf_quant_type(quant)
    return is_gguf_repo_name(model)


def local_dir_path_of(model: str) -> str | None:
    """The local directory of a local-directory GGUF reference, or None.

    ``/path/to/dir:Q4_K_M`` → ``/path/to/dir`` — the quant is embedded in
    the reference, so an existence check (e.g. capability validation) must
    target the directory alone, not ``"<dir>:<quant>"``.
    """
    model = (model or "").strip()
    if not is_local_gguf_dir_ref(model):
        return None
    if ":" in model:
        return model.rsplit(":", 1)[0]
    return model


def is_gguf_repo_name(model: str) -> bool:
    """Whether a bare repo id follows the ``…-GGUF`` / ``…_GGUF`` naming convention.

    Every major GGUF publisher (unsloth, bartowski, QuantFactory, huihui-ai,
    …) suffices its repository *name* with ``-GGUF`` (some use ``_GGUF``). The
    marker must be the end of the name, not a substring anywhere: a repository
    whose name merely contains ``gguf`` (``org/gguf-tools``,
    ``acme/GGUFactory-7B``, ``org/some_gguf_thing``) is not a GGUF repository.
    A substring match here is not harmless — a false positive makes
    :func:`resolve_gguf_spec` fail a plain model with "pin a quant" for a quant
    it does not have.
    """
    repo = repo_id_of(model)
    if "/" not in repo:
        return False
    name = repo.rsplit("/", 1)[1].strip().lower()
    return name.endswith("-gguf") or name.endswith("_gguf")


def is_gguf_model(model: str) -> bool:
    """Syntactic GGUF detection: file reference, remote reference, local
    directory reference, or the ``…-GGUF`` repo naming convention."""
    model = (model or "").strip()
    return (
        is_gguf_file_ref(model) or is_remote_gguf_ref(model) or is_local_gguf_dir_ref(model) or is_gguf_repo_name(model)
    )


def is_explicit_gguf_ref(model: str) -> bool:
    """Whether the reference carries its own quant/file information.

    For these, no file listing is needed to resolve the serve target: the
    file reference names its file, the remote ``repo:quant`` its quant, and
    the local directory reference ``/path/dir:<quant>`` its quant (a bare
    ``…-GGUF`` directory its whole content).
    """
    return is_gguf_file_ref(model) or is_remote_gguf_ref(model) or is_local_gguf_dir_ref(model)


def repo_id_of(model: str) -> str:
    """Reduce any GGUF model reference to its HuggingFace repo id.

    ``unsloth/Qwen3-8B-GGUF:Q4_K_M`` → ``unsloth/Qwen3-8B-GGUF``
    ``unsloth/Qwen3-8B-GGUF/Qwen3-8B-00001-of-00002-Q4_K_M.gguf`` → ``unsloth/Qwen3-8B-GGUF``
    """
    model = (model or "").strip()
    if ":" in model:
        model = model.rsplit(":", 1)[0]
    if model.lower().endswith(".gguf") and "/" in model:
        model = model.rsplit("/", 1)[0]
    return model


def hf_cache_dir_name(model: str) -> str:
    """HuggingFace cache directory name for *model*.

    The single source of the cache-directory key. It is keyed on
    :func:`repo_id_of`, so every form of a reference (bare repo,
    ``repo:quant``, ``repo/file.gguf``) maps to the same ``models--org--name``
    directory that the startup prefetch fills. The capability cache check and
    the RAM cache must derive the directory the same way, or two of the
    reference forms land in a directory the prefetch never populates. Non-GGUF
    references are unchanged (repo_id_of returns them as-is).
    """
    return "models--" + repo_id_of(model).replace("/", "--")


def quant_from_filename(filename: str) -> str | None:
    """Extract the quant type from a GGUF file name, when present.

    ``Qwen3-8B-Q4_K_M.gguf`` → ``Q4_K_M``;
    ``Qwen3-8B-Q4_K_M-00001-of-00004.gguf`` → ``Q4_K_M`` (shard suffix dropped);
    ``gpt2.Q8_0.gguf`` → ``Q8_0`` (dot-separated naming).
    Returns None for files without a recognizable quant (tokenizer.gguf,
    README.md, …).
    """
    name = (filename or "").rsplit("/", 1)[-1].strip()
    if not name.lower().endswith(".gguf"):
        return None
    stem = name[: -len(".gguf")]
    shard = _SHARD_SUFFIX_RE.search(stem)
    if shard:
        stem = stem[: shard.start()]
    # Dash separation is the standard; some publishers (e.g. QuantFactory)
    # use a dot instead. Dash wins when both are present (Qwen3.5-4B-…).
    # Quant names are case-insensitive in file names — the download patterns
    # match Q4_K_M and q4_k_m alike — so normalize before the vocabulary
    # match and keep the canonical uppercase form as the resolved quant.
    for sep in ("-", "."):
        if sep not in stem:
            continue
        tail = stem.rsplit(sep, 1)[-1].upper()
        if is_valid_gguf_quant_type(tail) or is_nonstandard_gguf_quant_type(tail):
            return tail
    return None


def candidate_quants(filenames: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """(quant, total_size) pairs available across *filenames*, de-duplicated.

    *filenames* are ``(name, size)`` pairs. The total size is summed over a
    quant's files (its shards) so :func:`select_quant` compares whole-quants,
    not single shards. Multimodal projector files (``mmproj*.gguf``) are
    excluded: they are a different model part and their quant (often F16) is
    not the backbone's.
    """
    order: list[str] = []
    sizes: dict[str, int] = {}
    for filename, size in filenames or []:
        base = (filename or "").rsplit("/", 1)[-1].lower()
        if "mmproj" in base:
            continue
        quant = quant_from_filename(filename)
        if not quant:
            continue
        if quant not in sizes:
            order.append(quant)
            sizes[quant] = 0
        sizes[quant] += int(size)
    return [(quant, sizes[quant]) for quant in order]


def select_quant(candidates: list[tuple[str, int]], preferred: str = "") -> str | None:
    """Pick the quant to serve from *candidates* ``(quant, size)`` pairs.

    An explicit *preferred* value is authoritative (the operator knows the
    repo even if the listing is stale or partial). Otherwise the first match
    in :data:`_PREFERRED_QUANTS` wins. With no match the smallest file is
    returned: the Hub lists larger (often unquantised, e.g. ``BF16``) variants
    first, so listing order would tend to the largest file — the least likely
    to load on the node's cards. The smallest quant is the most likely to fit.
    The tie-break on the name keeps the choice deterministic.
    """
    cands = [(quant, int(size)) for quant, size in (candidates or []) if quant]
    pref = (preferred or "").strip().upper()
    if pref:
        return pref
    if not cands:
        return None
    present = {quant for quant, _ in cands}
    for quant in _PREFERRED_QUANTS:
        if quant in present:
            return quant
    quant, _ = min(cands, key=lambda c: (c[1], c[0]))
    return quant


def _active_revision(refs_dir: Path) -> str | None:
    """The revision a repo's ``refs`` currently point at, or None if unclear.

    ``refs/main`` is preferred; a single other ref (a default branch not named
    ``main``) is the fallback. Ambiguous or absent refs yield None, so the
    caller treats the local listing as unavailable rather than guessing which
    of several cached revisions is the current one.
    """
    main_ref = refs_dir / "main"
    if main_ref.is_file():
        try:
            return main_ref.read_text().strip() or None
        except OSError:
            return None
    try:
        refs = [p for p in refs_dir.iterdir() if p.is_file()]
    except OSError:
        return None
    if len(refs) != 1:
        return None
    try:
        return refs[0].read_text().strip() or None
    except OSError:
        return None


def list_cached_model_weights(
    hf_home: str | None,
    model: str,
) -> tuple[list[tuple[str, int]], list[str]] | None:
    """Weight-format evidence of *model*'s active snapshot in the local HF cache.

    ``(gguf_files, non_gguf_weights)`` — ``(name, size)`` pairs of the
    snapshot's GGUF files (possibly empty) plus the names of its non-GGUF
    backbone weight files (see :func:`is_non_gguf_backbone_weight`) — or None
    when the model directory does not exist under
    ``<hf_home>/hub/models--<org>--<name>`` (model not downloaded yet) or its
    active revision cannot be resolved. The caller may then fall back to a
    remote listing. Both lists are authoritative when returned: an empty GGUF
    list proves the repo holds no GGUF weights, an empty weight list proves it
    holds no transformers backbone.

    Only the snapshot the repo's ``refs`` currently point at is walked
    recursively. Walking every cached revision instead would merge files from
    obsolete revisions, so a quant removed from the active branch could still
    be offered from a stale snapshot and selected for a ``repo:quant`` target
    the repository no longer serves. GGUF repositories often keep their weights
    in subdirectories (``quants/``), which this bounded walk still reaches.
    Names are snapshot-relative (``quants/Qwen3-8B-Q4_K_M.gguf``); the quant
    helpers basename their input, so the prefix is harmless. Sizes let
    :func:`select_quant` order the fallback by file size instead of relying on
    listing order.
    """
    if not hf_home:
        return None
    repo = repo_id_of(model)
    if "/" not in repo:
        return None
    repo_dir = Path(hf_home) / "hub" / hf_cache_dir_name(model)
    revision = _active_revision(repo_dir / "refs")
    if not revision:
        return None
    snapshot = repo_dir / "snapshots" / revision
    if not snapshot.is_dir():
        return None
    gguf_sizes: dict[str, int] = {}
    non_gguf_weights: set[str] = set()
    try:
        for entry in snapshot.rglob("*"):
            try:
                # stat() follows the snapshot symlink into blobs/
                if not entry.is_file():
                    continue
                size = entry.stat().st_size
            except OSError:
                continue
            if size <= 0:
                continue
            name = str(entry.relative_to(snapshot))
            base = name.rsplit("/", 1)[-1].lower()
            if base.endswith(".gguf"):
                gguf_sizes[name] = size
            elif is_non_gguf_backbone_weight(base):
                non_gguf_weights.add(name)
    except OSError:
        return None
    return sorted(gguf_sizes.items()), sorted(non_gguf_weights)


def list_cached_gguf_files(hf_home: str | None, model: str) -> list[tuple[str, int]] | None:
    """(name, size) pairs of *model*'s GGUF files in the local HF cache.

    Returns the (possibly empty) list of ``(name, size)`` pairs when the model
    directory exists under ``<hf_home>/hub/models--<org>--<name>``, and None
    when it does not (model not downloaded yet) or its active revision cannot
    be resolved — the caller may then fall back to a remote listing. An empty
    list is authoritative: the repo is cached and contains no GGUF weights.
    See :func:`list_cached_model_weights` for the walk itself.
    """
    result = list_cached_model_weights(hf_home, model)
    return None if result is None else result[0]


def list_cached_non_gguf_weights(hf_home: str | None, model: str) -> list[str] | None:
    """Non-GGUF backbone weight file names in *model*'s active snapshot.

    Same availability semantics as :func:`list_cached_gguf_files`; an empty
    list is authoritative (the snapshot holds no transformers backbone).
    """
    result = list_cached_model_weights(hf_home, model)
    return None if result is None else result[1]


def is_gguf_ref_cached(hf_home: str | None, model: str) -> bool | None:
    """Whether an explicit GGUF reference's concrete weights are cached.

    ``repo:quant`` and ``repo/file.gguf`` references name a specific quant or
    file, and Hugging Face snapshots can be partial — the startup prefetch
    stores only the quants its models selected, so a repository directory
    holding ``Q4_K_M`` does not satisfy ``repo:Q8_0`` of the same repo. This
    checks the active snapshot for the concrete target instead of the
    repository directory:

    - ``repo:quant`` — the cached files carry the quant, complete: a
      single-file quant needs its file, a sharded quant needs every index of
      its ``-N-of-M`` family in one directory (a partial or path-scattered
      download still counts as missing so the idempotent prefetch completes
      it).
    - ``repo/file.gguf`` — the named file is cached; for a sharded name the
      whole family in one directory, which the plugin's loader expands the
      first shard to.

    A local directory reference is a filesystem fact, not a Hub cache: it is
    True when the directory (the path without any ``:quant`` suffix) exists,
    False when it does not — the embedded quant's files are validated by the
    plugin at load time.

    Returns True when the snapshot proves the reference loadable, False when
    the active snapshot is present but lacks the quant or file (a partial
    cache of a different quant), and None when the local listing is
    unavailable (repo not cached, active revision unresolvable) or the model
    is not a remote explicit reference — callers treat False and None alike
    (missing), since only a prefetch can then (re)build the cache.
    """
    model = (model or "").strip()
    if is_local_gguf_dir_ref(model):
        directory = local_dir_path_of(model)
        return directory is not None and os.path.isdir(directory)
    if not (is_remote_gguf_ref(model) or is_remote_gguf_file_ref(model)):
        return None
    listing = list_cached_gguf_files(hf_home, model)
    if listing is None:
        return None
    if is_remote_gguf_ref(model):
        quant = model.rsplit(":", 1)[1].upper()
        # The loader reads a sharded quant from one directory, so every
        # index 1..total must sit in a single path — shards scattered across
        # directories (or duplicate indices filling a count) do not load.
        indices_by_dir: dict[str, set[int]] = {}
        shard_total = 0
        for name, _ in listing:
            base = name.rsplit("/", 1)[-1]
            if "mmproj" in base.lower() or quant_from_filename(base) != quant:
                continue
            shard = _SHARD_INDEX_RE.search(base)
            if shard is None:
                # A non-sharded file of the quant is a complete model.
                return True
            index, shard_total = _shard_marker_parts(shard.group(0))
            directory = name.rsplit("/", 1)[0] if "/" in name else ""
            indices_by_dir.setdefault(directory, set()).add(index)
        return any(all(index in indices for index in range(1, shard_total + 1)) for indices in indices_by_dir.values())
    requested = model.rsplit("/", 1)[1].lower()
    shard = _SHARD_INDEX_RE.search(requested)
    if shard is None:
        # Membership check: the named file anywhere in the snapshot.
        return requested in {name.rsplit("/", 1)[-1].lower() for name, _ in listing}
    key = _SHARD_INDEX_RE.sub("-of-", requested)
    _, total = _shard_marker_parts(shard.group(0))
    # The loader reads the family from the directory it finds the requested
    # file in, so every index 1..total must sit in ONE directory — shards
    # across paths or duplicate indices inflating a basename count do not
    # make the model loadable.
    indices_by_dir: dict[str, set[int]] = {}
    for name, _ in listing:
        lowered = name.lower()
        base = lowered.rsplit("/", 1)[-1]
        if _SHARD_INDEX_RE.sub("-of-", base) != key:
            continue
        index, _ = _shard_marker_parts(_SHARD_INDEX_RE.search(base).group(0))
        directory = lowered.rsplit("/", 1)[0] if "/" in lowered else ""
        indices_by_dir.setdefault(directory, set()).add(index)
    return any(all(index in indices for index in range(1, total + 1)) for indices in indices_by_dir.values())


def gguf_capability_target(
    hf_home: str | None,
    model: str,
    pinned_quant: str = "",
) -> str | None:
    """The concrete reference a GGUF capability's cache check must prove.

    Feeds :func:`is_gguf_ref_cached`, which the caller applies to the result:

    - explicit references (``repo:quant`` / ``repo/file.gguf``) → themselves;
    - a bare ``…-GGUF`` repository → ``<repo>:<quant>`` with the operator
      pin when it is a valid quant, else the quant the spec resolver
      auto-selects from the active cached listing — the one the lane will
      actually serve;
    - the bare repository itself when the listing cannot prove a target
      (unresolvable, or holding only auxiliary files):
      :func:`is_gguf_ref_cached` reports that as not cached, so the
      capability stays missing and the prefetch can (re)build it;
    - a local directory reference → itself: :func:`is_gguf_ref_cached`
      proves the directory (without the quant suffix) exists on the host,
      which is the whole proof a local path can offer;
    - ``None`` when the model is not a GGUF concern (plain model, or a
      repository whose authoritative listing holds no GGUF files at all — the
      resolver serves that as a plain model) — the caller applies its regular
      directory check.
    """
    model = (model or "").strip()
    if is_remote_gguf_ref(model) or is_remote_gguf_file_ref(model):
        return model
    if is_local_gguf_dir_ref(model):
        return model
    if not is_gguf_repo_name(model):
        return None
    pinned = (pinned_quant or "").strip()
    if pinned:
        # A pin the plugin would reject cannot load either way, so it
        # changes nothing the cache check can prove — the directory check
        # stands and the lane fails at spawn with the plugin's own error.
        if not is_remote_gguf_ref(f"{model}:{pinned}"):
            return None
        return f"{model}:{pinned}"
    listing = list_cached_gguf_files(hf_home, model)
    if not listing:
        # An authoritative EMPTY listing makes the resolver serve the repo
        # as a plain model (the directory check is the right proof); an
        # absent listing (None) proves nothing (the bare repo stays missing).
        return None if listing is not None else model
    quant = select_quant(candidate_quants(listing))
    if quant:
        return f"{model}:{quant}"
    # Cached but holding no backbone quant: the resolver fails the lane on
    # this listing, so the capability must stay missing — not be excused by
    # the repository directory alone.
    return model


def effective_hf_home(explicit: str | None, default: str = "") -> str:
    """HF cache root to consult for a local GGUF listing.

    Precedence: an explicit root (the RAM cache / operator override) > the
    inherited ``HF_HOME`` environment variable > *default* (the resolved
    persistent cache). Returns an empty string when nothing is set, so the
    caller can fall back to a HuggingFace Hub listing. Respecting the
    inherited ``HF_HOME`` keeps the listing lookup in the same directory the
    lane and the startup prefetch actually use. Each candidate is stripped
    before the truthiness check so a blank value falls through to the next.
    """
    return (explicit or "").strip() or os.environ.get("HF_HOME", "").strip() or (default or "").strip()


def needs_hub_listing(local_listing: list[tuple[str, int]] | None, model: str) -> bool:
    """Whether to fetch *model*'s GGUF file listing from the HuggingFace Hub.

    A listing the local cache produced — non-empty OR empty — is authoritative
    (an empty one proves the repo holds no GGUF weights), so only an absent
    listing (``None``) for a repo whose name follows the ``…-GGUF`` convention
    triggers a Hub fetch. This keeps locally cached models resolvable offline
    and stops redundant boot-time downloads.
    """
    return local_listing is None and is_gguf_repo_name(model)


@lru_cache(maxsize=64)
def fetch_repo_gguf_files(repo_id: str) -> tuple[tuple[str, int], ...]:
    """List ``(path, size)`` pairs of *repo_id*'s ``.gguf`` files on the Hub.

    Network call (cached per process). Raises on Hub errors — callers decide
    whether an unavailable listing is fatal or falls back to a configured
    ``gguf_quant``. The tree listing is used (rather than the lighter
    file-name listing) so each file carries its size: :func:`select_quant`
    orders the no-preference fallback by file size, and only the tree exposes
    that.
    """
    from huggingface_hub import HfApi  # noqa: PLC0415 — transitive dep, keep lazy

    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    pairs: list[tuple[str, int]] = []
    for entry in api.list_repo_tree(repo_id, recursive=True):
        path = getattr(entry, "path", None)
        size = getattr(entry, "size", None)
        if path and path.lower().endswith(".gguf") and size is not None:
            pairs.append((path, int(size)))
    return tuple(sorted(pairs))


def download_allow_patterns(model: str, quant: str) -> list[str] | None:
    """HF ``allow_patterns`` to download only *model*'s GGUF weights.

    Returns None when the model is not a GGUF reference (a full repo download
    is correct then). Mirrors the plugin's download_gguf pattern set so the
    prefetch and the plugin resolve to the same files.

    A file reference that names one shard of a multi-file quant (``…-00001-of-
    00002.gguf``) is expanded to a pattern covering every shard of the family,
    so the prefetch fetches the complete model instead of a single shard the
    lane would then have to download at startup (or fail on offline).
    """
    model = (model or "").strip()
    if is_gguf_file_ref(model):
        basename = model.rsplit("/", 1)[1] if "/" in model else model
        if _SHARD_INDEX_RE.search(basename):
            # Wildcard the shard indices so the pattern matches the whole
            # family; the leading * (fnmatch crosses path separators) covers
            # weights kept in a subdirectory.
            return ["*" + _SHARD_INDEX_RE.sub("-*-of-*", basename)]
        return [basename]
    if not is_gguf_model(model):
        return None
    quantized = quant or ""
    if not quantized:
        return None
    prefixes = ("*.", "*-")
    suffixes = ("-*", "")
    patterns = [
        f"{prefix}{qt}{suffix}.gguf"
        for qt in (quantized.upper(), quantized.lower())
        for prefix, suffix in itertools.product(prefixes, suffixes)
    ]
    return patterns


@dataclass(frozen=True)
class GgufServeSpec:
    """Resolved serving form of a GGUF model.

    ``serve_ref`` is what ``vllm serve`` receives; ``served_model_name`` is
    the alias that keeps the lane reachable under the model name the
    orchestrator registered; ``tokenizer`` is the HF repo passed as
    ``--tokenizer`` (also the HF config source for the plugin) when set.
    """

    model: str
    serve_ref: str
    quant: str | None = None
    tokenizer: str | None = None
    served_model_name: str | None = None


def resolve_gguf_spec(
    model: str,
    *,
    gguf_quant: str = "",
    gguf_tokenizer: str = "",
    gguf_file_names: list[tuple[str, int]] | None = None,
    non_gguf_weight_names: list[str] | None = None,
) -> GgufServeSpec | None:
    """Resolve the serve reference for a lane model, or None when it is not GGUF.

    * ``gguf_quant`` — operator-pinned quant for a bare GGUF repository.
    * ``gguf_tokenizer`` — HF repo to pass as ``--tokenizer`` (recommended:
      the base model, whose tokenizer and config the plugin then uses
      instead of converting them from GGUF metadata).
    * ``gguf_file_names`` — ``(name, size)`` pairs of the model's ``.gguf``
      files. None means the listing is unavailable (nothing cached, Hub
      listing failed); a list — possibly empty — is authoritative.
    * ``non_gguf_weight_names`` — names of the listing's non-GGUF backbone
      weight files (``model.safetensors``, ``pytorch_model.bin``, …). None
      means unknown (no evidence either way); a list — possibly empty — is
      authoritative.

    Raises ValueError when the model is detected as a GGUF repository but no
    quant can be determined — serving a bare repo without a quant is
    impossible (the plugin requires ``repo:quant`` or an explicit file), so
    the lane must fail with an actionable message instead of a vLLM error.
    """
    model = (model or "").strip()
    if not model:
        return None
    tokenizer = (gguf_tokenizer or "").strip() or None
    quant_override = (gguf_quant or "").strip()

    if is_explicit_gguf_ref(model):
        if is_remote_gguf_ref(model):
            # Canonicalize the quant to its uppercase form so vllm/the plugin
            # receive the same reference whether the operator typed it upper-
            # or lowercase; the download patterns already match both cases.
            repo, quant = model.rsplit(":", 1)
            quant = quant.upper()
            return GgufServeSpec(
                model=model,
                serve_ref=f"{repo}:{quant}",
                quant=quant,
                tokenizer=tokenizer,
            )
        if is_local_gguf_dir_ref(model):
            # A local directory reference is a filesystem fact, not a Hub
            # reference: the embedded quant is taken from the reference
            # itself (no listing — local or Hub — can resolve it), and the
            # serve reference keeps the dir:quant form the plugin parses.
            directory = local_dir_path_of(model) or model
            if ":" in model:
                quant = model.rsplit(":", 1)[1].upper()
                return GgufServeSpec(
                    model=model,
                    serve_ref=f"{directory}:{quant}",
                    quant=quant,
                    tokenizer=tokenizer,
                )
            # A bare …-GGUF directory serves its content as-is.
            return GgufServeSpec(model=model, serve_ref=directory, quant=None, tokenizer=tokenizer)
        return GgufServeSpec(model=model, serve_ref=model, quant=None, tokenizer=tokenizer)

    looks_like_gguf_repo = is_gguf_repo_name(model)
    # An authoritative listing (a list — from the local cache or the Hub) that
    # contains no GGUF files is proof the repo is not a GGUF model, even if its
    # name follows the convention: the name alone no longer gets the benefit of
    # the doubt once the listing actually resolved. Treating only a cached empty
    # listing as disproving left an empty *Hub* result standing as a false
    # positive. An unavailable listing (None) does not disprove the name.
    if gguf_file_names is not None and not gguf_file_names:
        return None
    # Consistent with candidate_quants() below: auxiliary artifacts
    # (tokenizer.gguf, mmproj projectors) are not backbone weights, so a
    # listing that holds only those is not proof of GGUF weights. Counting
    # any non-empty listing instead would misread an ordinary repo with just
    # a cached tokenizer as GGUF and fail at spawn time on quant resolution.
    has_gguf_files = bool(candidate_quants(gguf_file_names))
    if not looks_like_gguf_repo and not has_gguf_files:
        return None
    if not looks_like_gguf_repo and any(is_non_gguf_backbone_weight(name) for name in non_gguf_weight_names or []):
        # A plain-named repository whose listing holds non-GGUF backbone
        # weights is a transformers model that also bundles GGUF files: the
        # plain name refers to the backbone, so the GGUF files are an
        # additional format and the model is not a GGUF one. Auxiliary weight
        # files (mmproj, adapters) do not name the model and never
        # disqualify. A ``…-GGUF`` named repository is the operator's explicit
        # GGUF choice and keeps that preference, and an explicit repo:quant /
        # repo/file.gguf reference always wins (resolved above).
        return None

    if quant_override:
        quant = quant_override.upper()
    else:
        quant = select_quant(candidate_quants(gguf_file_names))
        if quant is None:
            raise ValueError(
                f"Cannot determine a GGUF quantization for {model!r}: the repository listing "
                "is unavailable and no quant is configured. Pin one under "
                f"engines.vllm.model_overrides.{model}.gguf_quant (e.g. Q4_K_M), or address "
                f"the model directly as '{model}:<quant_type>'."
            )
    return GgufServeSpec(model=model, serve_ref=f"{model}:{quant}", quant=quant, tokenizer=tokenizer)
