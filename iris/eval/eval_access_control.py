"""
Adversarial access-control checks for the global-search retrieval and pipeline
(Phase 4 of the results-gathering plan). Each case is a pass/fail assertion;
the output table goes directly into the thesis results chapter.

Cases:
  A  course isolation — results never leak from courses outside the access context
  B  empty course list — no results at all
  C  release-date filtering — future-release units hidden from students,
     visible to staff (uses the Artemis-provided `now` override; no data mutation)
  D  SKIP_AI independence — no LLM call is made on the skip path (token list empty)
  E  classifier fail-open — missing model directory falls back to TRIGGER_AI

Usage: .venv/bin/python eval/eval_access_control.py
"""

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APPLICATION_YML_PATH", str(REPO_ROOT / "application.local.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(REPO_ROOT / "llm_config.local.yml"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from iris.config import settings  # noqa: E402

settings.set_env_vars()

import logging  # noqa: E402

for noisy in ("httpx", "weaviate", "langfuse", "urllib3", "openai", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("iris").setLevel(logging.WARNING)

from iris.domain.search.lecture_search_dto import AccessContext  # noqa: E402
from iris.domain.search.search_intent_dto import SearchIntent  # noqa: E402
from iris.pipeline.global_search_pipeline import GlobalSearchPipeline  # noqa: E402
from iris.retrieval.lecture.lecture_global_search_retrieval import (  # noqa: E402
    LectureGlobalSearchRetrieval,
)
from iris.vector_database.database import VectorDatabase  # noqa: E402

RESULTS: list[tuple[str, str, bool, str]] = []  # (case, description, passed, detail)


def record(case: str, description: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((case, description, passed, detail))
    print(
        f"  [{'PASS' if passed else 'FAIL'}] {case}: {description}"
        + (f" — {detail}" if detail else "")
    )


def ctx(
    course_ids: list[int],
    student: list[int] | None = None,
    staff: list[int] | None = None,
    now: datetime | None = None,
) -> AccessContext:
    return AccessContext(
        courseIds=course_ids,
        editorCourseIds=staff or [],
        taCourseIds=[],
        studentCourseIds=student if student is not None else course_ids,
        staffCourseIds=staff or [],
        now=now,
    )


def unit_ids(results) -> set[int]:
    return {dto.lecture_unit.id for _, dto in results if dto.lecture_unit}


def course_ids_of(results) -> set[int]:
    return {dto.course.id for _, dto in results if dto.course}


def main() -> None:
    client = VectorDatabase().get_client()
    retriever = LectureGlobalSearchRetrieval(client, local=True)

    # ── A: course isolation ────────────────────────────────────────────────────
    print("\nCase A — course isolation")
    r7 = retriever.search(
        "gradient descent optimization", limit=20, access_context=ctx([7])
    )
    record("A1", "student of course 7 gets results", len(r7) > 0, f"{len(r7)} results")
    record(
        "A2",
        "all results belong to course 7",
        course_ids_of(r7) <= {7},
        f"courses seen: {course_ids_of(r7)}",
    )
    r_other = retriever.search(
        "gradient descent optimization", limit=20, access_context=ctx([999])
    )
    record(
        "A3",
        "non-existent course id yields nothing",
        len(r_other) == 0,
        f"{len(r_other)} results",
    )
    r9 = retriever.search(
        "design patterns software engineering", limit=20, access_context=ctx([9])
    )
    record(
        "A4",
        "course 9 context never returns course 7 content",
        7 not in course_ids_of(r9),
        f"courses seen: {course_ids_of(r9)}",
    )

    # ── B: empty course list ───────────────────────────────────────────────────
    print("\nCase B — empty course list")
    r_empty = retriever.search("gradient descent", limit=20, access_context=ctx([]))
    record(
        "B1",
        "empty courseIds returns zero results",
        len(r_empty) == 0,
        f"{len(r_empty)} results",
    )

    # ── C: release-date filtering (uses Artemis-provided `now`, real data) ─────
    print("\nCase C — release-date filtering")
    units_col = client.collections.get("LectureUnits")
    future_units: dict[int, tuple[int, datetime]] = {}
    for o in units_col.iterator():
        rd = o.properties.get("release_date")
        cid = o.properties.get("course_id")
        uid = o.properties.get("lecture_unit_id") or o.properties.get("unit_id")
        if rd is not None and uid is not None and cid is not None:
            rd = rd if rd.tzinfo else rd.replace(tzinfo=timezone.utc)
            future_units[int(uid)] = (int(cid), rd)
    if not future_units:
        record("C0", "release-dated units exist in test data", False, "none found")
    else:
        # Pick a `now` before the earliest release date so ALL dated units count
        # as unreleased, and search each affected course broadly.
        earliest = min(rd for _, rd in future_units.values())
        fake_now = earliest.replace(year=earliest.year - 1)
        affected_courses = sorted({cid for cid, _ in future_units.values()})
        leaked, hidden, staff_visible = [], [], []
        for cid in affected_courses:
            dated_units = {u for u, (c, _) in future_units.items() if c == cid}
            as_student = retriever.search(
                "lecture content overview introduction",
                limit=50,
                access_context=ctx([cid], student=[cid], now=fake_now),
            )
            as_staff = retriever.search(
                "lecture content overview introduction",
                limit=50,
                access_context=ctx([cid], student=[], staff=[cid], now=fake_now),
            )
            leaked += [u for u in unit_ids(as_student) if u in dated_units]
            hidden += [u for u in dated_units if u not in unit_ids(as_student)]
            staff_visible += [u for u in unit_ids(as_staff) if u in dated_units]
        record(
            "C1",
            "unreleased units hidden from students",
            len(leaked) == 0,
            f"{len(hidden)} hidden, {len(leaked)} leaked "
            f"(now={fake_now.date()}, dated units={len(future_units)})",
        )
        record(
            "C2",
            "same units visible to staff (filter is role-scoped)",
            len(staff_visible) > 0,
            f"{len(staff_visible)} dated unit(s) retrievable as staff",
        )

    # ── D: SKIP_AI independence ────────────────────────────────────────────────
    print("\nCase D — SKIP_AI path makes no LLM call")
    pipeline = GlobalSearchPipeline(client, local=True)
    pipeline.tokens = []
    resp = pipeline(
        query="Lecture 4",
        limit=5,
        intent=SearchIntent.SKIP_AI,
        access_context=ctx([7]),
        prefetched_entities=[],
    )
    record("D1", "SKIP_AI returns no answer", resp.answer is None, "")
    record(
        "D2",
        "SKIP_AI consumed zero LLM tokens",
        len(pipeline.tokens) == 0,
        f"token entries: {len(pipeline.tokens)}",
    )
    record(
        "D3",
        "SKIP_AI still returns search results",
        len(resp.sources) > 0,
        f"{len(resp.sources)} sources",
    )

    # ── E: classifier fail-open ────────────────────────────────────────────────
    print("\nCase E — classifier fail-open")
    code = (
        "import sys, os; sys.path.insert(0, 'src');"
        "from iris.pipeline.shared.global_search_intent_classifier import classify;"
        "print(classify('what is gradient descent').value)"
    )
    env = dict(os.environ, INTENT_MODEL_DIR="/nonexistent/path")
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=120,
    )
    record(
        "E1",
        "missing model dir falls open to TRIGGER_AI",
        out.stdout.strip().endswith("trigger_ai"),
        f"output: {out.stdout.strip()[-30:] or out.stderr.strip()[-60:]}",
    )

    client.close()

    n_pass = sum(1 for _, _, p, _ in RESULTS if p)
    print(f"\n{'=' * 60}\nAccess control: {n_pass}/{len(RESULTS)} checks passed")
    out_path = REPO_ROOT / "eval/results/access_control.md"
    lines = [
        "# Access-control adversarial checks\n",
        f"- date: {datetime.now().isoformat(timespec='seconds')}\n",
        "| case | check | result | detail |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {c} | {d} | {'PASS' if p else 'FAIL'} | {detail} |"
        for c, d, p, detail in RESULTS
    ]
    lines.append(f"\n**{n_pass}/{len(RESULTS)} passed**")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {out_path}")
    sys.exit(0 if n_pass == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
