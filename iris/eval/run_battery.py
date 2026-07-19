"""E2 — Automated eval runner for the global-search golden battery.

Runs `eval/data/global_search_battery.yaml` against a DEPLOYED Iris instance
through the real endpoints (no log reading, no manual eyeballing) and writes
a metrics report + raw results archive (implementation plan tasks E2.1-E2.4).

Paths:
  * list   — POST {base}/api/v1/search/lectures  (synchronous)
  * answer — POST {base}/api/v1/pipelines/global-search/run (202 + webhook).
             The runner impersonates Artemis: it starts a local HTTP receiver
             and sets settings.artemisBaseUrl to --callback-url, so the
             FINISHED/FAILED status update lands back here. This requires the
             Iris host to be able to reach --callback-url (run the runner on
             the same host, or use `ssh -R 8977:localhost:8977 <server>` and
             pass --callback-url http://localhost:8977).

Usage:
  python eval/run_battery.py --base-url http://localhost:8000 \
      --token "$IRIS_TOKEN" --split heldout --label baseline
  python eval/run_battery.py --selftest        # metric logic, no network

Outcome classification (answer path, from the terminal callback):
  answered          FINISHED with a non-empty answer
  no_sources        FINISHED, no answer, zero sources (the honest empty state)
  null_with_sources FINISHED, no answer, sources present (SKIP_AI intent or
                    the LLM null-gate — indistinguishable over the wire; the
                    report counts it separately from no_sources)
  failed / timeout  FAILED callback / no terminal callback in --answer-timeout

Metrics (E2.2) and acceptance gates (E2.3) are computed per run and written to
docs/global-search/eval-runs/<utc-stamp>-<label>/{results.json,report.md}.
Answer-language checking uses an EVAL-SIDE heuristic (script + stopwords);
detection is banned in the product, measurement here is fine — ambiguous
cases are reported as `manual`.
"""

# Dev tool, not service code: relax cosmetic lint that fights black/f-strings.
# pylint: disable=inconsistent-quotes,missing-class-docstring,invalid-name

from __future__ import annotations

import argparse
import json
import re
import statistics
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - battery is YAML; keep failure loud
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
BATTERY = ROOT / "eval" / "data" / "global_search_battery.yaml"
RUNS_DIR = ROOT / "docs" / "global-search" / "eval-runs"

LIST_CLASSES_OUTCOMES = {"list_relevant", "list_any"}

# E2.3 acceptance gates, applied when the run covers the held-out split.
GATES = [
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


def detect_language(text: str) -> str:
    """Eval-side answer-language heuristic: 'ar' | 'de' | 'en' | 'unknown'."""
    if not text:
        return "unknown"
    arabic = len(re.findall(r"[؀-ۿ]", text))
    if arabic > len(text) * 0.15:
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


def norm(s: str | None) -> str:
    return (s or "").casefold().strip()


def source_matches(expect: dict, source: dict) -> bool:
    """A source hit counts when the expected course or unit name matches."""
    course = norm(source.get("course", {}).get("name"))
    unit = norm(source.get("lectureUnit", {}).get("name"))
    want_course, want_unit = norm(expect.get("course")), norm(expect.get("unit"))
    if want_unit and want_unit == unit:
        return True
    if want_course and want_course == course:
        return True
    return False


# --------------------------------------------------------------------------- #
# Transports
# --------------------------------------------------------------------------- #
class CallbackReceiver:
    """Minimal Artemis impersonator: collects status updates per run id."""

    PATH_RE = re.compile(
        r"/api/iris/internal/pipelines/global-search/runs/([^/]+)/status$"
    )

    def __init__(self, port: int):
        self.results: dict[str, dict] = {}
        self.events: dict[str, threading.Event] = {}
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server API
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                m = receiver.PATH_RE.search(self.path)
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                if not m:
                    return
                run_id = m.group(1)
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {"parse_error": body[:200].decode(errors="replace")}
                state = payload.get("runState") or payload.get("run_state")
                if state in ("FINISHED", "FAILED"):
                    receiver.results[run_id] = payload
                    receiver.events.setdefault(run_id, threading.Event()).set()

            def log_message(self, *_):  # silence per-request stderr noise
                pass

        bind_all = ("0.0.0.0", port)  # nosec B104 - eval receiver via tunnel
        self.server = ThreadingHTTPServer(bind_all, Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def wait(self, run_id: str, timeout: float) -> dict | None:
        event = self.events.setdefault(run_id, threading.Event())
        if event.wait(timeout):
            return self.results.get(run_id)
        return None

    def close(self):
        self.server.shutdown()


def post_json(
    url: str, token: str, payload: dict, timeout: float
) -> tuple[int, object]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            body = resp.read()
            return resp.status, (json.loads(body) if body.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode(errors="replace")
    except Exception as e:  # noqa: BLE001 - recorded per query, run continues
        return -1, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# Per-query execution
# --------------------------------------------------------------------------- #
def run_list_query(base: str, token: str, item: dict, timeout: float) -> dict:
    t0 = time.perf_counter()
    status, body = post_json(
        f"{base}/api/v1/search/lectures",
        token,
        {"query": item["text"], "limit": 10},
        timeout,
    )
    ms = (time.perf_counter() - t0) * 1000
    rec = {"path": "list", "http": status, "ms": round(ms)}
    if status != 200 or not isinstance(body, list):
        rec.update(outcome="error", detail=str(body)[:200])
        return rec
    rec["results"] = [
        {
            "course": r.get("course", {}).get("name"),
            "unit": r.get("lectureUnit", {}).get("name"),
        }
        for r in body[:10]
    ]
    rec["outcome"] = "list_ok"
    expect = item["expect"]
    if item["expect"]["outcome"] == "list_relevant":
        hits = [i for i, r in enumerate(body[:5]) if source_matches(expect, r)]
        rec["top1_hit"] = bool(hits and hits[0] == 0)
        rec["top5_hit"] = bool(hits)
    return rec


def run_answer_query(
    base: str,
    token: str,
    item: dict,
    receiver: CallbackReceiver,
    callback_url: str,
    timeout: float,
) -> dict:
    run_id = f"eval-{uuid.uuid4().hex[:12]}"
    t0 = time.perf_counter()
    status, body = post_json(
        f"{base}/api/v1/pipelines/global-search/run",
        token,
        {
            "query": item["text"],
            "limit": 5,
            "settings": {
                "authenticationToken": run_id,
                "artemisBaseUrl": callback_url.rstrip("/"),
                "selection": "CLOUD_AI",
                "variant": "default",
            },
        },
        30,
    )
    if status != 202:
        return {
            "path": "answer",
            "http": status,
            "outcome": "error",
            "detail": str(body)[:200],
            "ms": round((time.perf_counter() - t0) * 1000),
        }
    payload = receiver.wait(run_id, timeout)
    ms = (time.perf_counter() - t0) * 1000
    rec: dict = {"path": "answer", "http": status, "ms": round(ms)}
    if payload is None:
        rec["outcome"] = "timeout"
        return rec
    state = payload.get("runState") or payload.get("run_state")
    answer = payload.get("answer") or payload.get("result")
    sources = payload.get("sources") or []
    rec["sources"] = [
        {
            "course": s.get("course", {}).get("name"),
            "unit": s.get("lectureUnit", {}).get("name"),
        }
        for s in sources
    ]
    if state == "FAILED":
        rec["outcome"] = "failed"
    elif answer:
        rec["outcome"] = "answered"
        rec["answer"] = answer
        rec["answer_language"] = detect_language(answer)
    elif sources:
        rec["outcome"] = "null_with_sources"
    else:
        rec["outcome"] = "no_sources"
    if rec["outcome"] == "answered" and (
        item["expect"].get("course") or item["expect"].get("unit")
    ):
        matched = sum(1 for s in sources if source_matches(item["expect"], s))
        rec["used_source_match"] = bool(matched)
        rec["used_source_precision"] = matched / len(sources) if sources else 0.0
    return rec


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def judge(item: dict, rec: dict) -> str:
    """pass / fail_false_answer / fail_false_null / fail_ranking /
    soft_llm_null / manual / infra_error"""
    expected = item["expect"]["outcome"]
    got = rec.get("outcome")
    if got in ("error", "timeout", "failed"):
        return "infra_error"
    if expected == "answered":
        if got == "answered":
            want_lang = item["expect"].get("answer_language")
            got_lang = rec.get("answer_language")
            if want_lang and got_lang not in (want_lang, "unknown"):
                return "fail_language"
            return "pass"
        return "fail_false_null"
    if expected == "no_sources":
        if got == "no_sources":
            return "pass"
        if got == "null_with_sources":
            return "soft_llm_null"  # user sees no answer, but the gate missed
        return "fail_false_answer"
    if expected == "grounded_negative_or_no_sources":
        if got in ("no_sources", "null_with_sources"):
            return "pass"
        return "manual"  # answered — negativity needs human judgment
    if expected == "list_relevant":
        if got != "list_ok":
            return "infra_error"
        return "pass" if rec.get("top5_hit") else "fail_ranking"
    if expected == "list_any":
        return "pass" if got == "list_ok" else "infra_error"
    return "manual"


def summarize(records: list[dict]) -> dict:
    def rate(num, den):
        return round(num / den, 4) if den else None

    list_ms = [
        r["rec"]["ms"]
        for r in records
        if r["rec"].get("path") == "list" and r["rec"].get("outcome") == "list_ok"
    ]
    ans_ms = [
        r["rec"]["ms"]
        for r in records
        if r["rec"].get("path") == "answer"
        and r["rec"].get("outcome") not in ("timeout", "error")
    ]

    nocontent = [r for r in records if r["item"]["expect"]["outcome"] == "no_sources"]
    answered_expected = [
        r for r in records if r["item"]["expect"]["outcome"] == "answered"
    ]
    list_rel = [
        r
        for r in records
        if r["item"]["expect"]["outcome"] == "list_relevant"
        and r["rec"].get("outcome") == "list_ok"
    ]
    lang_checked = [
        r
        for r in records
        if r["rec"].get("answer_language")
        and r["item"]["expect"].get("answer_language")
    ]

    def pctl(vals, p):
        if not vals:
            return None
        vals = sorted(vals)
        return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]

    verdicts = [r["verdict"] for r in records]
    return {
        "queries": len(records),
        "verdicts": {v: verdicts.count(v) for v in sorted(set(verdicts))},
        "false_answer_rate": rate(
            sum(1 for r in nocontent if r["verdict"] == "fail_false_answer"),
            len(nocontent),
        ),
        "gate_miss_rate_soft_null": rate(
            sum(1 for r in nocontent if r["verdict"] == "soft_llm_null"),
            len(nocontent),
        ),
        "false_null_rate": rate(
            sum(1 for r in answered_expected if r["verdict"] == "fail_false_null"),
            len(answered_expected),
        ),
        "list_top5_hit_rate": rate(
            sum(1 for r in list_rel if r["rec"].get("top5_hit")), len(list_rel)
        ),
        "list_top1_hit_rate": rate(
            sum(1 for r in list_rel if r["rec"].get("top1_hit")), len(list_rel)
        ),
        "answer_language_accuracy": rate(
            sum(
                1
                for r in lang_checked
                if r["rec"]["answer_language"]
                in (r["item"]["expect"]["answer_language"], "unknown")
            ),
            len(lang_checked),
        ),
        "used_source_precision_mean": (
            round(
                statistics.mean(
                    [
                        r["rec"]["used_source_precision"]
                        for r in records
                        if "used_source_precision" in r["rec"]
                    ]
                ),
                4,
            )
            if any("used_source_precision" in r["rec"] for r in records)
            else None
        ),
        "list_p50_ms": pctl(list_ms, 0.5),
        "list_p95_ms": pctl(list_ms, 0.95),
        "answer_p50_ms": pctl(ans_ms, 0.5),
        "answer_p95_ms": pctl(ans_ms, 0.95),
    }


def gates_table(summary: dict) -> list[dict]:
    rows = []
    for metric, op, threshold in GATES:
        value = summary.get(metric)
        if value is None:
            rows.append(
                {
                    "metric": metric,
                    "value": None,
                    "gate": f"{op} {threshold}",
                    "status": "n/a",
                }
            )
            continue
        ok = value <= threshold if op == "<=" else value >= threshold
        rows.append(
            {
                "metric": metric,
                "value": value,
                "gate": f"{op} {threshold}",
                "status": "PASS" if ok else "FAIL",
            }
        )
    return rows


def write_report(
    out_dir: Path, meta: dict, summary: dict, gates: list[dict], records: list[dict]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps(
            {"meta": meta, "summary": summary, "gates": gates, "records": records},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    lines = [
        f"# Eval run — {meta['label']}",
        "",
        f"UTC {meta['started_utc']} | base `{meta['base_url']}` | "
        f"split `{meta['split']}` | battery v{meta['battery_version']} | "
        f"{summary['queries']} queries",
        "",
        "## Gates",
        "",
        "| metric | value | gate | status |",
        "|---|---|---|---|",
    ]
    for g in gates:
        lines.append(f"| {g['metric']} | {g['value']} | {g['gate']} | {g['status']} |")
    lines += [
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(summary, indent=2),
        "```",
        "",
        "## Failures & manual-review items",
        "",
    ]
    for r in records:
        if r["verdict"].startswith("fail") or r["verdict"] in ("manual", "infra_error"):
            rec = r["rec"]
            lines.append(
                f"- `{r['item']['id']}` [{r['verdict']}] "
                f"({r['item']['class']}, {r['item']['split']}) "
                f"{r['item']['text']!r} -> {rec.get('outcome')} "
                f"{('answer: ' + rec['answer'][:120] + '…') if rec.get('answer') else ''}"
            )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
def selftest() -> None:
    """E5: metric/judge logic on synthetic fixtures — no network."""
    item_answer = {
        "id": "t1",
        "class": "concept-direct",
        "split": "heldout",
        "text": "q",
        "expect": {"outcome": "answered", "course": "C1", "answer_language": "en"},
    }
    item_control = {
        "id": "t2",
        "class": "no-content",
        "split": "heldout",
        "text": "q",
        "expect": {"outcome": "no_sources"},
    }
    item_list = {
        "id": "t3",
        "class": "navigational-title",
        "split": "heldout",
        "text": "q",
        "expect": {"outcome": "list_relevant", "unit": "U1"},
    }
    cases = [
        (item_answer, {"outcome": "answered", "answer_language": "en"}, "pass"),
        (
            item_answer,
            {"outcome": "answered", "answer_language": "de"},
            "fail_language",
        ),
        (item_answer, {"outcome": "no_sources"}, "fail_false_null"),
        (item_control, {"outcome": "no_sources"}, "pass"),
        (item_control, {"outcome": "answered"}, "fail_false_answer"),
        (item_control, {"outcome": "null_with_sources"}, "soft_llm_null"),
        (item_list, {"outcome": "list_ok", "top5_hit": True}, "pass"),
        (item_list, {"outcome": "list_ok", "top5_hit": False}, "fail_ranking"),
        (item_answer, {"outcome": "timeout"}, "infra_error"),
    ]
    for item, rec, want in cases:
        got = judge(item, rec)
        assert (
            got == want
        ), f"{item['id']}: {rec} -> {got}, wanted {want}"  # nosec B101 - selftest
    assert (
        detect_language("Der Kurs ist eine Einführung und wird gut") == "de"
    )  # nosec B101 - selftest
    assert (
        detect_language("The course is an introduction to the topic") == "en"
    )  # nosec B101 - selftest
    assert (
        detect_language("التعلم المعزز هو نوع من تعلم الآلة") == "ar"
    )  # nosec B101 - selftest
    assert source_matches(  # nosec B101 - selftest
        {"course": "C1"}, {"course": {"name": "c1"}, "lectureUnit": {"name": "x"}}
    )
    assert not source_matches(  # nosec B101 - selftest
        {"course": "C1"}, {"course": {"name": "other"}, "lectureUnit": {"name": "x"}}
    )
    r = summarize(
        [
            {
                "item": item_control,
                "rec": {"path": "answer", "ms": 100, "outcome": "no_sources"},
                "verdict": "pass",
            },
            {
                "item": item_control,
                "rec": {"path": "answer", "ms": 200, "outcome": "answered"},
                "verdict": "fail_false_answer",
            },
        ]
    )
    assert r["false_answer_rate"] == 0.5  # nosec B101 - selftest
    print("selftest OK (9 judge cases, language + matching + summary)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--token", default="")
    ap.add_argument(
        "--split", choices=["heldout", "calibration", "all"], default="heldout"
    )
    ap.add_argument(
        "--classes", default="", help="comma-separated class filter (default all)"
    )
    ap.add_argument("--paths", choices=["both", "list", "answer"], default="both")
    ap.add_argument("--label", default="run")
    ap.add_argument(
        "--callback-url",
        default="",
        help="URL where the IRIS HOST can reach this runner "
        "(required for the answer path)",
    )
    ap.add_argument("--callback-port", type=int, default=8977)
    ap.add_argument("--answer-timeout", type=float, default=60.0)
    ap.add_argument("--http-timeout", type=float, default=15.0)
    ap.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="pause between queries (rate-limit hygiene)",
    )
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if yaml is None:
        raise SystemExit("pyyaml required: pip install pyyaml")
    if not args.token:
        raise SystemExit("--token required (the Iris API token)")

    battery = yaml.safe_load(BATTERY.read_text(encoding="utf-8"))
    items = battery["queries"]
    if args.split != "all":
        items = [x for x in items if x["split"] == args.split]
    if args.classes:
        keep = {c.strip() for c in args.classes.split(",")}
        items = [x for x in items if x["class"] in keep]

    receiver = None
    if args.paths in ("both", "answer"):
        if not args.callback_url:
            print(
                "NOTE: no --callback-url — answer-path queries will be "
                "skipped (list-only run)"
            )
        else:
            receiver = CallbackReceiver(args.callback_port)

    records = []
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for i, item in enumerate(items, 1):
        is_list = item["expect"]["outcome"] in LIST_CLASSES_OUTCOMES
        if is_list and args.paths in ("both", "list"):
            rec = run_list_query(args.base_url, args.token, item, args.http_timeout)
        elif not is_list and receiver is not None:
            rec = run_answer_query(
                args.base_url,
                args.token,
                item,
                receiver,
                args.callback_url,
                args.answer_timeout,
            )
        else:
            continue
        verdict = judge(item, rec)
        records.append({"item": item, "rec": rec, "verdict": verdict})
        print(
            f"[{i:3d}/{len(items)}] {item['id']} {item['class']:18s} "
            f"{verdict:18s} {rec.get('ms', '-'):>6}ms  {item['text'][:50]!r}"
        )
        time.sleep(args.sleep)

    if receiver:
        receiver.close()
    if not records:
        raise SystemExit("nothing ran (check --paths / --callback-url / filters)")

    summary = summarize(records)
    gates = gates_table(summary) if args.split == "heldout" else []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = RUNS_DIR / f"{stamp}-{args.label}"
    meta = {
        "label": args.label,
        "started_utc": started,
        "base_url": args.base_url,
        "split": args.split,
        "paths": args.paths,
        "battery_version": battery["meta"]["version"],
    }
    write_report(out_dir, meta, summary, gates, records)
    print(f"\nreport: {out_dir}/report.md")
    print(json.dumps(summary, indent=2))
    for g in gates:
        print(
            f"  GATE {g['metric']:28s} {str(g['value']):>8} {g['gate']:>9} "
            f"{g['status']}"
        )


if __name__ == "__main__":
    main()
