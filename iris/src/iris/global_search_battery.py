"""In-process golden-battery runner for global search (E2, server-side mode).

The eval battery (E1, `global_search_battery_data.py`) normally runs from the
outside via `eval/run_battery.py` — but that needs an API token and callback
reachability. On the test branch neither exists (config is not editable and
there is no server access), so this module runs the SAME battery inside the
service process, where auth does not apply, and emits the full report as
`[battery]` log lines — the established deploy-and-paste-logs loop.

Started from the app lifespan in a daemon thread when
`settings.global_search_battery_on_startup` is non-empty ("heldout" |
"calibration" | "all"). Every step is defensively wrapped: the battery must
never break or delay startup, and a single bad query must not stop the run.

Path selection mirrors production exactly:
  * list-expected queries  -> LectureGlobalSearchRetrieval.search(limit=10)
  * answer-expected queries -> intent classifier + GlobalSearchPipeline,
    the same code path the /pipelines/global-search/run worker takes —
    with the bonus that the INTENT is visible here (the wire hides it).
"""

from __future__ import annotations

import re
import statistics
import time

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.domain.search.search_intent_dto import SearchIntent
from iris.global_search_battery_data import QUERIES, VERSION

logger = get_logger(__name__)

_PREFIX = "[battery]"
_SLEEP_BETWEEN_QUERIES_S = 0.5
_STARTUP_DELAY_S = 45.0  # let census/embedding warm-up finish first

# E2.3 acceptance gates (heldout split).
_GATES = [
    ("false_answer_rate", "<=", 0.05),
    ("false_null_rate", "<=", 0.05),
    ("list_top5_hit_rate", ">=", 0.90),
    ("answer_language_accuracy", ">=", 0.95),
    ("list_p95_ms", "<=", 2500),
    ("answer_p95_ms", "<=", 8000),
]

_DE_STOPS = {
    "der",
    "die",
    "das",
    "und",
    "ist",
    "ein",
    "eine",
    "mit",
    "für",
    "nicht",
    "werden",
    "wird",
    "sind",
    "auf",
    "im",
    "des",
    "den",
}
_EN_STOPS = {
    "the",
    "is",
    "a",
    "an",
    "and",
    "of",
    "to",
    "in",
    "that",
    "for",
    "with",
    "are",
    "on",
    "as",
    "it",
    "this",
    "by",
}


def _detect_language(text: str) -> str:
    """Eval-side heuristic ('ar'|'de'|'en'|'unknown') — measurement only,
    never product logic (language detection is deliberately banned there)."""
    if not text:
        return "unknown"
    if len(re.findall(r"[؀-ۿ]", text)) > len(text) * 0.15:
        return "ar"
    words = re.findall(r"[a-zA-Zäöüß]+", text.lower())
    if not words:
        return "unknown"
    de = sum(w in _DE_STOPS for w in words)
    en = sum(w in _EN_STOPS for w in words)
    if de > en and de >= 2:
        return "de"
    if en > de and en >= 2:
        return "en"
    return "unknown"


def _norm(value: str | None) -> str:
    return (value or "").casefold().strip()


def _source_matches(
    expect: dict, course_name: str | None, unit_name: str | None
) -> bool:
    want_course, want_unit = _norm(expect.get("course")), _norm(expect.get("unit"))
    if want_unit and want_unit == _norm(unit_name):
        return True
    if want_course and want_course == _norm(course_name):
        return True
    return False


def _judge(item: dict, rec: dict) -> str:
    expected = item["expect"]["outcome"]
    got = rec.get("outcome")
    if got in ("error", "timeout", "failed"):
        return "infra_error"
    if expected == "answered":
        if got == "answered":
            want = item["expect"].get("answer_language")
            got_lang = rec.get("answer_language")
            if want and got_lang not in (want, "unknown"):
                return "fail_language"
            return "pass"
        return "fail_false_null"
    if expected == "no_sources":
        if got == "no_sources":
            return "pass"
        if got == "null_with_sources":
            return "soft_llm_null"
        return "fail_false_answer"
    if expected == "grounded_negative_or_no_sources":
        return "pass" if got in ("no_sources", "null_with_sources") else "manual"
    if expected == "list_relevant":
        if got != "list_ok":
            return "infra_error"
        return "pass" if rec.get("top5_hit") else "fail_ranking"
    if expected == "list_any":
        return "pass" if got == "list_ok" else "infra_error"
    return "manual"


def _pctl(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))]


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _summarize(records: list[tuple[dict, dict, str]]) -> dict:
    list_ms = [
        rec["ms"]
        for _, rec, _ in records
        if rec.get("path") == "list" and rec.get("outcome") == "list_ok"
    ]
    ans_ms = [
        rec["ms"]
        for _, rec, _ in records
        if rec.get("path") == "answer"
        and rec.get("outcome") not in ("timeout", "error")
    ]
    nocontent = [
        (i, r, v) for i, r, v in records if i["expect"]["outcome"] == "no_sources"
    ]
    answer_exp = [
        (i, r, v) for i, r, v in records if i["expect"]["outcome"] == "answered"
    ]
    list_rel = [
        (i, r, v)
        for i, r, v in records
        if i["expect"]["outcome"] == "list_relevant" and r.get("outcome") == "list_ok"
    ]
    lang = [
        (i, r, v)
        for i, r, v in records
        if r.get("answer_language") and i["expect"].get("answer_language")
    ]
    verdicts = [v for _, _, v in records]
    precisions = [
        r["used_source_precision"]
        for _, r, _ in records
        if "used_source_precision" in r
    ]
    return {
        "queries": len(records),
        "verdicts": {v: verdicts.count(v) for v in sorted(set(verdicts))},
        "false_answer_rate": _rate(
            sum(1 for _, _, v in nocontent if v == "fail_false_answer"), len(nocontent)
        ),
        "gate_miss_rate_soft_null": _rate(
            sum(1 for _, _, v in nocontent if v == "soft_llm_null"), len(nocontent)
        ),
        "false_null_rate": _rate(
            sum(1 for _, _, v in answer_exp if v == "fail_false_null"), len(answer_exp)
        ),
        "list_top5_hit_rate": _rate(
            sum(1 for _, r, _ in list_rel if r.get("top5_hit")), len(list_rel)
        ),
        "list_top1_hit_rate": _rate(
            sum(1 for _, r, _ in list_rel if r.get("top1_hit")), len(list_rel)
        ),
        "answer_language_accuracy": _rate(
            sum(
                1
                for i, r, _ in lang
                if r["answer_language"] in (i["expect"]["answer_language"], "unknown")
            ),
            len(lang),
        ),
        "used_source_precision_mean": (
            round(statistics.mean(precisions), 4) if precisions else None
        ),
        "list_p50_ms": _pctl(list_ms, 0.5),
        "list_p95_ms": _pctl(list_ms, 0.95),
        "answer_p50_ms": _pctl(ans_ms, 0.5),
        "answer_p95_ms": _pctl(ans_ms, 0.95),
    }


def _run_list_query(retriever, item: dict) -> dict:
    t0 = time.perf_counter()
    try:
        results = retriever.search(query=item["text"], limit=10)
    except Exception as e:  # noqa: BLE001 - one bad query must not stop the run
        return {
            "path": "list",
            "outcome": "error",
            "detail": f"{type(e).__name__}: {e}"[:200],
            "ms": round((time.perf_counter() - t0) * 1000),
        }
    rec = {
        "path": "list",
        "outcome": "list_ok",
        "ms": round((time.perf_counter() - t0) * 1000),
        "hits": len(results),
    }
    if item["expect"]["outcome"] == "list_relevant":
        expect = item["expect"]
        hit_positions = [
            i
            for i, r in enumerate(results[:5])
            if _source_matches(expect, r.course.name, r.lecture_unit.name)
        ]
        rec["top1_hit"] = bool(hit_positions and hit_positions[0] == 0)
        rec["top5_hit"] = bool(hit_positions)
    return rec


def _run_answer_query(pipeline, retriever, item: dict) -> dict:
    # pylint: disable-next=import-outside-toplevel
    from iris.pipeline.shared.global_search_intent_classifier import (
        classify as classify_intent,
    )

    t0 = time.perf_counter()
    try:
        intent = classify_intent(item["text"])
        if intent == SearchIntent.SKIP_AI:
            sources = retriever.search(query=item["text"], limit=5)
            answer = None
        else:
            result = pipeline(query=item["text"], limit=5, intent=intent)
            answer, sources = result.answer, result.sources
    except Exception as e:  # noqa: BLE001 - one bad query must not stop the run
        return {
            "path": "answer",
            "outcome": "error",
            "detail": f"{type(e).__name__}: {e}"[:200],
            "ms": round((time.perf_counter() - t0) * 1000),
        }
    rec: dict = {
        "path": "answer",
        "intent": intent.value,
        "ms": round((time.perf_counter() - t0) * 1000),
        "sources": len(sources),
    }
    if answer:
        rec["outcome"] = "answered"
        rec["answer_language"] = _detect_language(answer)
        rec["answer_len"] = len(answer)
        expect = item["expect"]
        if (expect.get("course") or expect.get("unit")) and sources:
            matched = sum(
                1
                for s in sources
                if _source_matches(expect, s.course.name, s.lecture_unit.name)
            )
            rec["used_source_precision"] = round(matched / len(sources), 4)
    elif sources:
        rec["outcome"] = "null_with_sources"
    else:
        rec["outcome"] = "no_sources"
    return rec


def run_battery() -> None:
    """Run the configured split and log the full report. Never raises."""
    split = settings.global_search_battery_on_startup
    try:
        time.sleep(_STARTUP_DELAY_S)
        items = [dict(x) for x in QUERIES if split == "all" or x["split"] == split]
        logger.info(
            "%s START battery_version=%s split=%s queries=%d "
            "(in-process runner — no token/callback needed)",
            _PREFIX,
            VERSION,
            split,
            len(items),
        )
        # Imports deferred so a broken pipeline config cannot break startup
        # via this module's import chain.
        from iris.pipeline.global_search_pipeline import (  # noqa: E402 pylint: disable=import-outside-toplevel
            GlobalSearchPipeline,
        )

        # pylint: disable-next=import-outside-toplevel
        from iris.retrieval.lecture.lecture_global_search_retrieval import (
            LectureGlobalSearchRetrieval,
        )
        from iris.vector_database.database import (  # noqa: E402 pylint: disable=import-outside-toplevel
            VectorDatabase,
        )

        client = VectorDatabase().get_client()
        retriever = LectureGlobalSearchRetrieval(client)
        pipeline = GlobalSearchPipeline(client)

        records: list[tuple[dict, dict, str]] = []
        for n, item in enumerate(items, 1):
            is_list = item["expect"]["outcome"] in ("list_relevant", "list_any")
            rec = (
                _run_list_query(retriever, item)
                if is_list
                else _run_answer_query(pipeline, retriever, item)
            )
            verdict = _judge(item, rec)
            records.append((item, rec, verdict))
            logger.info(
                "%s [%d/%d] %s %s %s -> %s verdict=%s ms=%s%s%s",
                _PREFIX,
                n,
                len(items),
                item["id"],
                item["class"],
                repr(item["text"][:60]),
                rec.get("outcome"),
                verdict,
                rec.get("ms"),
                " intent=" + rec["intent"] if rec.get("intent") else "",
                " detail=" + rec["detail"] if rec.get("detail") else "",
            )
            time.sleep(_SLEEP_BETWEEN_QUERIES_S)

        summary = _summarize(records)
        logger.info("%s SUMMARY %s", _PREFIX, summary)
        if split == "heldout":
            for metric, op, threshold in _GATES:
                value = summary.get(metric)
                if value is None:
                    status = "n/a"
                else:
                    ok = value <= threshold if op == "<=" else value >= threshold
                    status = "PASS" if ok else "FAIL"
                logger.info(
                    "%s GATE %s=%s (%s %s) %s",
                    _PREFIX,
                    metric,
                    value,
                    op,
                    threshold,
                    status,
                )
        for item, rec, verdict in records:
            if verdict.startswith("fail") or verdict in ("manual", "infra_error"):
                logger.info(
                    "%s REVIEW %s [%s] %r -> %s%s",
                    _PREFIX,
                    item["id"],
                    verdict,
                    item["text"][:60],
                    rec.get("outcome"),
                    (
                        (" answer=" + repr(rec.get("answer_language")))
                        if rec.get("answer_language")
                        else ""
                    ),
                )
        logger.info("%s DONE", _PREFIX)
    except Exception as e:  # noqa: BLE001 - battery must never break the service
        logger.warning("%s aborted: %s", _PREFIX, e, exc_info=True)
