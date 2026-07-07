"""
End-to-end evaluation of the GlobalSearchPipeline on the 150-question suite.

Runs the PRODUCTION pipeline (__call__) — not a reimplementation — with per-phase
timing via instance-level wrappers and event counting via a logging handler.

Modes:
  full           production behavior (classifier + HyDE + answer LLM)
  no_hyde        HyDE LLM replaced by identity (raw query embedded at alpha 0.5)
  no_classifier  intent forced to TRIGGER_AI (measures the classifier's routing value)

Entity prefetch is simulated the way Artemis does it (IrisLectureSearchResource):
BM25 over Artemis_SearchableEntities filtered to {exercise, faq, exam, channel} and
the user's course IDs, limit 15.

Usage:
  .venv/bin/python eval/eval_answer_pipeline.py --modes full no_hyde no_classifier
  .venv/bin/python eval/eval_answer_pipeline.py --smoke   # 3 questions, mode=full
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APPLICATION_YML_PATH", str(REPO_ROOT / "application.local.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(REPO_ROOT / "llm_config.local.yml"))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval/data"))

from iris.config import settings  # noqa: E402

settings.set_env_vars()

for noisy in ("httpx", "weaviate", "langfuse", "urllib3", "openai", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from answer_suite import QUESTIONS  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402
from weaviate.classes.query import Filter  # noqa: E402

from iris.domain.search.lecture_search_dto import (  # noqa: E402
    AccessContext,
    CourseInfo,
    GlobalSearchSourceDTO,
)
from iris.domain.search.search_intent_dto import SearchIntent  # noqa: E402
from iris.pipeline.global_search_pipeline import GlobalSearchPipeline  # noqa: E402
from iris.vector_database.database import VectorDatabase  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval/results"

# Mirrors GlobalSearchService.IRIS_ENTITY_TYPES and ENTITY_PREFETCH_LIMIT in Artemis
IRIS_ENTITY_TYPES = ["exercise", "faq", "exam", "channel"]
ENTITY_PREFETCH_LIMIT = 15


# ─── Artemis entity-prefetch simulation ────────────────────────────────────────


class EntityPrefetcher:
    """BM25 over Artemis_SearchableEntities, as IrisLectureSearchResource does."""

    def __init__(self, client):
        self.collection = client.collections.get("Artemis_SearchableEntities")

    def fetch(
        self, query: str, access_context: AccessContext | None
    ) -> list[GlobalSearchSourceDTO]:
        filters = Filter.by_property("type").contains_any(IRIS_ENTITY_TYPES)
        if access_context is not None:
            ids = access_context.course_ids or []
            if not ids:
                return []
            filters = filters & Filter.by_property("course_id").contains_any(ids)
        try:
            res = self.collection.query.bm25(
                query, limit=ENTITY_PREFETCH_LIMIT, filters=filters
            )
        except Exception:
            return []
        out = []
        for o in res.objects:
            p = o.properties
            out.append(
                GlobalSearchSourceDTO(
                    sourceType=str(p.get("type") or "entity"),
                    entityId=int(p.get("entity_id") or 0),
                    course=CourseInfo(id=int(p.get("course_id") or 0), name=""),
                    title=str(p.get("title") or "").strip(),
                    snippet=str(p.get("description") or "") or None,
                )
            )
        return out


# ─── Instrumentation ───────────────────────────────────────────────────────────


EVENT_PATTERNS = {
    "hyde_fallback": re.compile(r"HyDE retrieval returned 0 sources"),
    "refusal_suppressed": re.compile(r"refusal detected", re.I),
    "json_parse_failed": re.compile(r"Failed to parse structured answer"),
    "json_repaired": re.compile(r"JSON repaired via LaTeX"),
}


class EventCounter(logging.Handler):
    def __init__(self):
        super().__init__()
        self.counts: dict[str, int] = {}

    def reset(self):
        self.counts = {}

    def emit(self, record):
        msg = record.getMessage()
        for name, pat in EVENT_PATTERNS.items():
            if pat.search(msg):
                self.counts[name] = self.counts.get(name, 0) + 1


class TimedRunnable(RunnableLambda):
    """Wraps a Runnable, accumulating wall time into `sink[key]`."""

    def __init__(self, inner, sink: dict, key: str):
        def _run(value):
            t0 = time.perf_counter()
            out = inner.invoke(value)
            sink[key] = sink.get(key, 0.0) + (time.perf_counter() - t0) * 1000
            return out

        super().__init__(_run)


def wrap_retriever(retriever, sink: dict) -> None:
    for name in ("search", "search_with_vector_override"):
        inner = getattr(retriever, name)

        def timed(*a, _inner=inner, **kw):
            t0 = time.perf_counter()
            out = _inner(*a, **kw)
            sink["retrieval_ms"] = (
                sink.get("retrieval_ms", 0.0) + (time.perf_counter() - t0) * 1000
            )
            return out

        setattr(retriever, name, timed)


# ─── Runner ────────────────────────────────────────────────────────────────────


@dataclass
class Result:
    query: str
    category: str
    expected: bool
    mode: str
    answered: bool = False
    correct: bool = False
    answer: str = ""
    n_sources: int = 0
    sources: list[dict] = field(default_factory=list)
    handoff: str = ""
    hyde_ms: float = 0.0
    retrieval_ms: float = 0.0
    answer_ms: float = 0.0
    total_ms: float = 0.0
    events: dict = field(default_factory=dict)
    error: str = ""


def build_pipeline(client, mode: str, sink: dict) -> GlobalSearchPipeline:
    p = GlobalSearchPipeline(client, local=True)
    wrap_retriever(p.retriever, sink)
    if mode == "no_hyde":
        # Identity "HyDE": the prompt value's last message is the raw user query,
        # so retrieval embeds the query itself at alpha 0.5 — the no-HyDE ablation.
        p.hyde_pipeline = RunnableLambda(lambda pv: pv.messages[-1].content)
        # hyde_llm is never invoked, so its .tokens stays None — skip accounting
        orig_append = p._append_tokens
        p._append_tokens = lambda tokens, pipe: (
            orig_append(tokens, pipe) if tokens is not None else None
        )
    else:
        p.hyde_pipeline = TimedRunnable(p.hyde_pipeline, sink, "hyde_ms")
    p.answer_pipeline = TimedRunnable(p.answer_pipeline, sink, "answer_ms")
    return p


def run_suite(client, mode: str, questions, counter: EventCounter) -> list[Result]:
    sink: dict = {}
    pipeline = build_pipeline(client, mode, sink)
    prefetcher = EntityPrefetcher(client)
    results = []
    for i, (query, ctx, category, expected) in enumerate(questions, 1):
        sink.clear()
        counter.reset()
        r = Result(query=query, category=category, expected=expected, mode=mode)
        t0 = time.perf_counter()
        try:
            entities = prefetcher.fetch(query, ctx)
            intent = SearchIntent.TRIGGER_AI if mode == "no_classifier" else None
            resp = pipeline(
                query=query,
                limit=5,
                intent=intent,
                access_context=ctx,
                prefetched_entities=entities,
            )
            r.answered = bool(resp.answer)
            r.answer = resp.answer or ""
            r.n_sources = len(resp.sources)
            r.sources = [
                {
                    "type": s.source_type,
                    "title": s.title,
                    "course_id": s.course.id,
                    "course": s.course.name or "",
                    "snippet": s.snippet or "",
                }
                for s in resp.sources
            ]
            r.handoff = resp.handoff.type.value if resp.handoff else ""
        except Exception as exc:
            r.error = str(exc)[:200]
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.hyde_ms = sink.get("hyde_ms", 0.0)
        r.retrieval_ms = sink.get("retrieval_ms", 0.0)
        r.answer_ms = sink.get("answer_ms", 0.0)
        r.correct = r.answered == r.expected
        r.events = dict(counter.counts)
        mark = "+" if r.correct else "-"
        print(
            f"[{i:3}/{len(questions)}] {mark} {mode:13s} "
            f"{'ans ' if r.answered else 'null'} {r.total_ms:6.0f}ms "
            f"[{category}] {query[:55]}",
            flush=True,
        )
        results.append(r)
    return results


# ─── Reporting ─────────────────────────────────────────────────────────────────


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def summarize(all_results: dict[str, list[Result]], lines: list[str]) -> None:
    for mode, results in all_results.items():
        ok = [r for r in results if not r.error]
        lines.append(f"\n## Mode: {mode}\n")
        if len(ok) < len(results):
            lines.append(f"- errors: {len(results) - len(ok)} queries failed")
        n_correct = sum(r.correct for r in ok)
        lines.append(
            f"- decision correctness: **{n_correct}/{len(ok)}** "
            f"({pct(n_correct / len(ok))})"
        )

        should = [r for r in ok if r.expected]
        should_not = [r for r in ok if not r.expected]
        ans_recall = sum(r.answered for r in should) / len(should) if should else 0
        answered_all = [r for r in ok if r.answered]
        ans_precision = (
            sum(r.expected for r in answered_all) / len(answered_all)
            if answered_all
            else 0
        )
        grounding_failures = sum(r.answered for r in should_not)
        lines.append(
            f"- answer recall (should-answer answered): {pct(ans_recall)} "
            f"({sum(r.answered for r in should)}/{len(should)})"
        )
        lines.append(
            f"- answer precision (answers that were expected): " f"{pct(ans_precision)}"
        )
        lines.append(
            f"- **grounding failures** (answered when null expected): "
            f"{grounding_failures}/{len(should_not)}"
        )

        lines.append("\n| category | n | correct | acc |")
        lines.append("|---|---|---|---|")
        for cat in sorted({r.category for r in ok}):
            sub = [r for r in ok if r.category == cat]
            c = sum(r.correct for r in sub)
            lines.append(f"| {cat} | {len(sub)} | {c} | {c / len(sub):.2f} |")

        import numpy as np

        for phase in ("hyde_ms", "retrieval_ms", "answer_ms", "total_ms"):
            vals = np.array([getattr(r, phase) for r in ok if getattr(r, phase) > 0])
            if len(vals):
                lines.append(
                    f"- {phase}: p50 {np.percentile(vals, 50):.0f} · "
                    f"p95 {np.percentile(vals, 95):.0f} · mean {vals.mean():.0f} "
                    f"(n={len(vals)})"
                )

        event_totals: dict[str, int] = {}
        for r in ok:
            for k, v in r.events.items():
                event_totals[k] = event_totals.get(k, 0) + v
        lines.append(f"- events: {event_totals or 'none'}")

        handoffs: dict[str, int] = {}
        for r in ok:
            if r.answered:
                handoffs[r.handoff or "none"] = handoffs.get(r.handoff or "none", 0) + 1
        lines.append(f"- handoff distribution (answered queries): {handoffs}")

    # paired comparison vs 'full'
    if "full" in all_results and len(all_results) > 1:
        ref = all_results["full"]
        for mode, results in all_results.items():
            if mode == "full":
                continue
            reg = [(a, b) for a, b in zip(ref, results) if a.correct and not b.correct]
            imp = [(a, b) for a, b in zip(ref, results) if not a.correct and b.correct]
            lines.append(
                f"\n### {mode} vs full: {len(reg)} regressions, "
                f"{len(imp)} improvements"
            )
            for _, b in reg:
                lines.append(f"- REG [{b.category}] {b.query[:70]}")
            for _, b in imp:
                lines.append(f"- IMP [{b.category}] {b.query[:70]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--modes",
        nargs="+",
        default=["full"],
        choices=["full", "no_hyde", "no_classifier"],
    )
    ap.add_argument("--smoke", action="store_true", help="3 questions only")
    ap.add_argument("--tag", default="", help="suffix for output filenames")
    args = ap.parse_args()

    questions = QUESTIONS[:3] if args.smoke else QUESTIONS
    counter = EventCounter()
    logging.getLogger("iris").addHandler(counter)
    logging.getLogger("iris").setLevel(logging.INFO)
    # keep console clean: iris logs go only to our counter
    logging.getLogger("iris").propagate = False

    client = VectorDatabase().get_client()
    all_results: dict[str, list[Result]] = {}
    try:
        for mode in args.modes:
            print(f"\n=== mode: {mode} ({len(questions)} questions) ===", flush=True)
            all_results[mode] = run_suite(client, mode, questions, counter)
    finally:
        client.close()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + (
        f"_{args.tag}" if args.tag else ""
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        "# GlobalSearchPipeline end-to-end evaluation",
        f"- date: {datetime.now().isoformat(timespec='seconds')}",
        f"- suite: {len(questions)} questions · modes: {', '.join(args.modes)}",
        "- entity prefetch: BM25 over Artemis_SearchableEntities "
        f"(types {IRIS_ENTITY_TYPES}, limit {ENTITY_PREFETCH_LIMIT}) — simulates "
        "Artemis IrisLectureSearchResource.prefetchEntities",
    ]
    summarize(all_results, lines)
    report = RESULTS_DIR / f"answer_eval_{stamp}.md"
    report.write_text("\n".join(lines), encoding="utf-8")

    # Full answers + sources for the LLM-judge phase
    jsonl = RESULTS_DIR / f"answers_{stamp}.jsonl"
    with open(jsonl, "w", encoding="utf-8") as f:
        for mode, results in all_results.items():
            for r in results:
                f.write(
                    json.dumps(
                        {
                            "mode": r.mode,
                            "query": r.query,
                            "category": r.category,
                            "expected": r.expected,
                            "answered": r.answered,
                            "correct": r.correct,
                            "answer": r.answer,
                            "sources": r.sources,
                            "handoff": r.handoff,
                            "hyde_ms": round(r.hyde_ms),
                            "retrieval_ms": round(r.retrieval_ms),
                            "answer_ms": round(r.answer_ms),
                            "total_ms": round(r.total_ms),
                            "events": r.events,
                            "error": r.error,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    csv_path = RESULTS_DIR / f"answer_eval_{stamp}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "mode",
                "category",
                "query",
                "expected",
                "answered",
                "correct",
                "n_sources",
                "handoff",
                "hyde_ms",
                "retrieval_ms",
                "answer_ms",
                "total_ms",
                "events",
                "error",
            ]
        )
        for results in all_results.values():
            for r in results:
                w.writerow(
                    [
                        r.mode,
                        r.category,
                        r.query,
                        r.expected,
                        r.answered,
                        r.correct,
                        r.n_sources,
                        r.handoff,
                        round(r.hyde_ms),
                        round(r.retrieval_ms),
                        round(r.answer_ms),
                        round(r.total_ms),
                        json.dumps(r.events),
                        r.error,
                    ]
                )

    print(f"\nReport: {report}\nAnswers: {jsonl}\nCSV: {csv_path}")


if __name__ == "__main__":
    main()
