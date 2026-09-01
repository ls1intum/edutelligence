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

# Multi-file shard suffix: …-Q4_K_M-00001-of-00004.gguf
_SHARD_SUFFIX_RE = re.compile(r"-\d+-of-\d+$")


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
    """Whether *model* is a ``<repo_id>:<quant_type>`` GGUF reference."""
    model = (model or "").strip()
    if not _REMOTE_GGUF_RE.fullmatch(model):
        return False
    quant_type = model.rsplit(":", 1)[1]
    return is_valid_gguf_quant_type(quant_type) or is_nonstandard_gguf_quant_type(quant_type)


def is_gguf_file_ref(model: str) -> bool:
    """Whether *model* names a GGUF file (local path or ``repo/file.gguf``)."""
    return (model or "").strip().lower().endswith(".gguf")


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
    """Syntactic GGUF detection: file reference, remote reference, or the
    ``…-GGUF`` repo naming convention."""
    model = (model or "").strip()
    return is_gguf_file_ref(model) or is_remote_gguf_ref(model) or is_gguf_repo_name(model)


def is_explicit_gguf_ref(model: str) -> bool:
    """Whether the reference carries its own quant/file information.

    For these, no file listing is needed to resolve the serve target.
    """
    return is_gguf_file_ref(model) or is_remote_gguf_ref(model)


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


def list_cached_gguf_files(hf_home: str | None, model: str) -> list[tuple[str, int]] | None:
    """(name, size) pairs of *model*'s GGUF files in the local HF cache.

    Returns the (possibly empty) list of ``(name, size)`` pairs when the model
    directory exists under ``<hf_home>/hub/models--<org>--<name>``, and None
    when it does not (model not downloaded yet — the caller may then fall
    back to a remote listing). An empty list is authoritative: the repo is
    cached and contains no GGUF weights. Each snapshot revision is walked
    recursively — GGUF repositories often keep their weights in
    subdirectories (``quants/``) — but never past it, so discovery stays
    bounded to this model and does not scan the whole cache. Names are
    snapshot-relative, so a nested file surfaces as
    ``quants/Qwen3-8B-Q4_K_M.gguf`` (the quant helpers basename their input,
    so the prefix is harmless). Sizes let :func:`select_quant` order the
    fallback by file size instead of relying on listing order.
    """
    if not hf_home:
        return None
    repo = repo_id_of(model)
    if "/" not in repo:
        return None
    snapshots = Path(hf_home) / "hub" / hf_cache_dir_name(model) / "snapshots"
    if not snapshots.is_dir():
        return None
    sizes: dict[str, int] = {}
    try:
        for rev_dir in snapshots.iterdir():
            if not rev_dir.is_dir():
                continue
            # Bounded to this revision, never the whole cache.
            for entry in rev_dir.rglob("*.gguf"):
                try:
                    # stat() follows the snapshot symlink into blobs/
                    size = entry.stat().st_size
                    if size > 0:
                        sizes[str(entry.relative_to(rev_dir))] = size
                except OSError:
                    continue
    except OSError:
        return None
    return sorted(sizes.items())


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
    """
    model = (model or "").strip()
    if is_gguf_file_ref(model):
        if "/" in model:
            return [model.rsplit("/", 1)[1]]
        return [model]
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
) -> GgufServeSpec | None:
    """Resolve the serve reference for a lane model, or None when it is not GGUF.

    * ``gguf_quant`` — operator-pinned quant for a bare GGUF repository.
    * ``gguf_tokenizer`` — HF repo to pass as ``--tokenizer`` (recommended:
      the base model, whose tokenizer and config the plugin then uses
      instead of converting them from GGUF metadata).
    * ``gguf_file_names`` — ``(name, size)`` pairs of the model's ``.gguf``
      files. None means the listing is unavailable (nothing cached, Hub
      listing failed); a list — possibly empty — is authoritative.

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
        quant = model.rsplit(":", 1)[1] if is_remote_gguf_ref(model) else None
        return GgufServeSpec(model=model, serve_ref=model, quant=quant, tokenizer=tokenizer)

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
