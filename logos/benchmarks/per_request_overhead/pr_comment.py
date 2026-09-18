#!/usr/bin/env python
"""CI gate + PR comment for the per-request overhead benchmark (issue #980).

Reads ``result.json`` (from ``LOGOS_BENCH_OUTPUT``, default ``reports/`` next
to this file) and:

  * with ``--check``: exits 0 while the overhead p50 is within the CI fail
    threshold (``FAIL_NS``), 1 above it — the blocking gate;
  * without the flag: posts (or edits the last, idempotent via the HTML
    anchor) one PR comment with the verdict, the phase table, and the gate
    result, then exits with the same gate code. A comment failure (e.g.
    fork PRs running with a read-only token) is logged and does not mask
    the gate.

Stdlib only, so it runs from the plain benchmark venv.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from report import FAIL_NS, GOAL_NS, verdict  # noqa: E402

_ANCHOR = "<!-- logos-overhead-bench -->"
_API_TIMEOUT_S = 30.0


def _load_result() -> Dict[str, Any]:
    out_dir = Path(os.environ.get("LOGOS_BENCH_OUTPUT") or (_HERE / "reports"))
    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"benchmark result not found: {result_path}")
    return json.loads(result_path.read_text())


def _gate(result: Dict[str, Any]) -> int:
    overhead = float(result["overhead"]["overhead_ns"])
    if overhead > FAIL_NS:
        print(
            f"GATE FAIL: overhead p50 {overhead / 1000.0:,.1f} µs exceeds the "
            f"CI fail threshold of {FAIL_NS / 1000.0:,.0f} µs "
            f"(goal < {GOAL_NS / 1000.0:,.0f} µs)"
        )
        return 1
    print(
        f"GATE PASS: overhead p50 {overhead / 1000.0:,.1f} µs "
        f"(goal < {GOAL_NS / 1000.0:,.0f} µs, CI fail threshold {FAIL_NS / 1000.0:,.0f} µs)"
    )
    return 0


def _top_phases(result: Dict[str, Any], limit: int = 10) -> List[Tuple[str, float, float]]:
    """Top phases by per-request p50: (name, p50 µs, share of the median request).

    The share denominator is the sum of the per-phase p50s — the budget of a
    *typical* request. Summing total_ns instead would be dominated by a single
    outlier request (e.g. a cold lane load inside the measurement window).
    """
    phases: Dict[str, Dict[str, float]] = result.get("phases", {})
    p50_sum_ns = sum(float(p.get("p50_ns", 0.0)) for p in phases.values())
    ranked = sorted(phases.items(), key=lambda kv: float(kv[1].get("p50_ns", 0.0)), reverse=True)
    rows = []
    for name, phase in ranked[:limit]:
        p50_ns = float(phase.get("p50_ns", 0.0))
        share = (p50_ns / p50_sum_ns * 100.0) if p50_sum_ns else 0.0
        rows.append((name, p50_ns / 1000.0, share))
    return rows


def _comment_markdown(result: Dict[str, Any]) -> str:
    overhead = float(result["overhead"]["overhead_ns"])
    logo = result["summary"]["logos"]
    direct = result["summary"]["direct"]
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[verdict(overhead)]
    lines = [
        f"## {icon} {verdict(overhead)} — Per-request forwarding overhead",
        "",
        f"**Overhead p50 = {overhead / 1000.0:,.1f} µs** — goal "
        f"< {GOAL_NS / 1000.0:,.0f} µs, CI fail threshold {FAIL_NS / 1000.0:,.0f} µs.",
        "",
        "| Path | p50 | samples |",
        "| --- | ---: | ---: |",
        f"| Logos (orchestrator → worker → back) | {logo['p50_ns'] / 1000.0:,.1f} µs | {int(logo['n'])} |",
        f"| Direct baseline (same payload, keep-alive) | {direct['p50_ns'] / 1000.0:,.1f} µs | {int(direct['n'])} |",
        "",
        "Top phases (per-request p50, share of the median request):",
        "",
        "| Phase | p50 | Share |",
        "| --- | ---: | ---: |",
    ]
    for name, p50_us, share in _top_phases(result):
        mark = " ⚠️" if share > 5.0 else ""
        lines.append(f"| `{name}` | {p50_us:,.1f} µs | {share:.1f}%{mark} |")
    lines += [
        "",
        "Scenario: `logosnode` provider, warm lane, no concurrent requests, "
        "non-streaming `POST /v1/chat/completions`. Overhead = median(Logos) − median(direct).",
        "",
        _ANCHOR,
    ]
    return "\n".join(lines)


def _api_request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=_API_TIMEOUT_S) as response:
        body = response.read().decode()
        return json.loads(body) if body else {}


def _pr_number() -> Optional[str]:
    explicit = os.environ.get("LOGOS_BENCH_PR_NUMBER")
    if explicit:
        return explicit
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        return None
    event = json.loads(Path(event_path).read_text())
    number = event.get("number") or (event.get("pull_request") or {}).get("number")
    return str(number) if number else None


def _find_last_bench_comment(api_comments: str, token: str) -> Optional[Dict[str, Any]]:
    """The newest issue comment carrying the anchor (idempotent edit target)."""
    page = 1
    while True:
        comments = _api_request("GET", f"{api_comments}?per_page=100&page={page}", token)
        if not comments:
            return None
        matching = [c for c in comments if _ANCHOR in (c.get("body") or "")]
        if matching:
            return matching[-1]
        if len(comments) < 100:
            return None
        page += 1


def _post_comment(markdown: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    # GITHUB_API_URL is the REST base (https://api.github.com on GitHub.com,
    # the matching base on Enterprise). GITHUB_SERVER_URL is the *web* URL —
    # appending /api/v3 to it would not resolve.
    server = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    number = _pr_number()
    if not token or not repo or not number:
        print("PR comment skipped (no GITHUB_TOKEN / GITHUB_REPOSITORY / PR number)")
        return
    api_comments = f"{server}/repos/{repo}/issues/{number}/comments"
    existing = _find_last_bench_comment(api_comments, token)
    if existing:
        _api_request(
            "PATCH",
            f"{server}/repos/{repo}/issues/comments/{existing['id']}",
            token,
            {"body": markdown},
        )
        print(f"PR comment updated (id={existing['id']})")
    else:
        _api_request("POST", api_comments, token, {"body": markdown})
        print("PR comment created")


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    try:
        result = _load_result()
    except FileNotFoundError as exc:
        # The gate must stay red when the benchmark produced nothing; the
        # comment step (which runs with `if: always()`) has nothing to post.
        if check_only:
            print(f"GATE FAIL: {exc}")
            return 1
        print(f"PR comment skipped ({exc})")
        return 0
    if check_only:
        return _gate(result)

    if os.environ.get("LOGOS_BENCH_PR_COMMENT_DRY_RUN") == "1":
        print(_comment_markdown(result))
        return _gate(result)
    try:
        _post_comment(_comment_markdown(result))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        # Fork PRs run read-only: the artifact and the gate still count.
        print(f"PR comment failed (continuing): {exc}")
    return _gate(result)


if __name__ == "__main__":
    sys.exit(main())
