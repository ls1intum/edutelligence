"""Access to the captured vLLM failure-log corpus.

The corpus is the oracle a GPU-less suite is built on: real startup failures,
each paired with the verdict the worker has to reach from it. Tests replay an
entry through the fake vLLM and assert the classification and the recovery
action, so a change to a fingerprint that would misfire in production fails
here first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CORPUS_DIR = Path(__file__).parent
MANIFEST = CORPUS_DIR / "manifest.yaml"


@dataclass(frozen=True)
class Expectation:
    fatal_cuda: bool
    poisoned_cache: bool
    cache_fingerprint: str | None
    broken_shards: bool


@dataclass(frozen=True)
class CorpusEntry:
    log: str
    summary: str
    source: str
    expect: Expectation
    #: Serve this through a pre-sharded lane. The broken-checkpoint detector is
    #: deliberately inert unless the lane is actually serving shards, so an
    #: entry testing it has to opt in.
    sharded: bool = False

    @property
    def path(self) -> Path:
        return CORPUS_DIR / self.log

    @property
    def id(self) -> str:
        """Stable pytest parametrisation id."""
        return self.log.removesuffix(".log").replace("/", ":")

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def benign(self) -> bool:
        return not (self.expect.fatal_cuda or self.expect.poisoned_cache or self.expect.broken_shards)


def _entry(raw: dict[str, Any]) -> CorpusEntry:
    expect = raw.get("expect", {})
    return CorpusEntry(
        log=raw["log"],
        summary=raw.get("summary", "").strip(),
        source=raw.get("source", "").strip(),
        sharded=bool(raw.get("sharded", False)),
        expect=Expectation(
            fatal_cuda=bool(expect.get("fatal_cuda", False)),
            poisoned_cache=bool(expect.get("poisoned_cache", False)),
            cache_fingerprint=expect.get("cache_fingerprint"),
            broken_shards=bool(expect.get("broken_shards", False)),
        ),
    )


def load() -> list[CorpusEntry]:
    raw = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    entries = [_entry(item) for item in raw.get("entries", [])]
    missing = [e.log for e in entries if not e.path.is_file()]
    if missing:
        raise FileNotFoundError(f"manifest.yaml references log file(s) that do not exist: {missing}")
    return entries


def orphan_logs() -> list[str]:
    """Log files on disk that no manifest entry claims.

    An unclassified log is a silently uncovered failure mode, so a test asserts
    this stays empty.
    """
    listed = {e.log for e in load()}
    on_disk = {str(p.relative_to(CORPUS_DIR)) for p in CORPUS_DIR.rglob("*.log")}
    return sorted(on_disk - listed)
