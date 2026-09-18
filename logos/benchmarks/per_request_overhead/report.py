"""Render the benchmark result as JSON + Markdown.

The Markdown report is the human-facing artifact: it carries p50/p95 goals,
the phase table (ns detail), and the run metadata.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

# Goals from the benchmark: p50 forwarding overhead < 10 ms and p95 < 20 ms.
GOAL_NS = 10_000_000
P95_GOAL_NS = 20_000_000
# The p50 goal is also the blocking CI threshold.
FAIL_NS = GOAL_NS


def ns_to_us(ns: float) -> str:
    return f"{ns / 1000.0:,.1f}"


def verdict(overhead_ns: float) -> str:
    if overhead_ns <= GOAL_NS:
        return "PASS"
    if overhead_ns <= FAIL_NS:
        return "WARN"
    return "FAIL"


def overall_verdict(overhead_p50_ns: float, overhead_p95_ns: float) -> str:
    """Return the combined verdict for the p50 and p95 service goals."""
    p50_verdict = verdict(overhead_p50_ns)
    if p50_verdict == "FAIL" or overhead_p95_ns > P95_GOAL_NS:
        return "FAIL"
    if p50_verdict == "WARN":
        return "WARN"
    return "PASS"


def build_markdown(result: Dict[str, Any]) -> str:
    """Render the full result dict (as produced by run_benchmark) to Markdown."""
    ov = result["overhead"]
    overhead_p50_ns = float(ov.get("overhead_p50_ns", ov["overhead_ns"]))
    overhead_p95_ns = float(ov.get("overhead_p95_ns", 0.0))
    verdict_str = overall_verdict(overhead_p50_ns, overhead_p95_ns)
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[verdict_str]
    phases = result.get("phases", {})

    lines: List[str] = []
    lines.append("# Per-Request Forwarding Overhead")
    lines.append("")
    lines.append(
        f"**{icon} {verdict_str}** — overhead p50 = **{ns_to_us(overhead_p50_ns)} µs**, "
        f"p95 = **{ns_to_us(overhead_p95_ns)} µs** "
        f"(goals: p50 < {ns_to_us(GOAL_NS)} µs, p95 < {ns_to_us(P95_GOAL_NS)} µs; "
        f"CI p50 fail threshold {ns_to_us(FAIL_NS)} µs)"
    )
    lines.append("")
    lines.append(
        f"Run at {result.get('generated_at', 'n/a')} · samples: "
        f"{ov['n_logos']} via Logos / {ov['n_direct']} direct baseline"
    )
    lines.append("")
    lines.append("| Metric | p50 | p95 | p99 |")
    lines.append("|---|---:|---:|---:|")
    for label, key in (("Via Logos (full path)", "logos"), ("Direct to lane (baseline)", "direct")):
        s = result["summary"][key]
        lines.append(
            f"| {label} | {ns_to_us(s['p50_ns'])} µs | {ns_to_us(s['p95_ns'])} µs | {ns_to_us(s['p99_ns'])} µs |"
        )
    lines.append("")

    if phases:
        lines.append("## Phase breakdown (p50 of per-request phase time, via Logos)")
        lines.append("")
        lines.append("| Phase | p50 | mean | count |")
        lines.append("|---|---:|---:|---:|")
        ordered = sorted(phases.items(), key=lambda kv: kv[1].get("p50_ns", 0.0), reverse=True)
        for name, agg in ordered[:25]:
            lines.append(
                f"| `{name}` | {ns_to_us(agg['p50_ns'])} µs | {ns_to_us(agg['mean_ns'])} µs | {int(agg['count'])} |"
            )
        lines.append("")

    lines.append("## Method")
    lines.append("")
    lines.append(
        "- Scenario: local logosnode provider, **warm lane** (model loaded, no other running "
        "requests), non-streaming `POST /v1/chat/completions`."
    )
    lines.append(
        "- Overhead p50/p95 = the matching percentile of via Logos minus the same "
        "percentile of the direct baseline, with interleaved blocks to cancel common-mode drift."
    )
    lines.append(
        "- No GPU host in CI: nvidia-smi and /proc-walk costs in the worker degrade to cheap "
        "no-ops (documented under-estimation); the optimizations remove most of that path anyway."
    )
    lines.append(f"- Env: `{json.dumps(result.get('env', {}), sort_keys=True)}`")
    lines.append("")
    return "\n".join(lines)


def write_reports(result: Dict[str, Any], out_dir: str) -> Dict[str, str]:
    """Write result.json + report.md into out_dir; returns the paths."""
    os.makedirs(out_dir, exist_ok=True)
    result = dict(result)
    result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json_path = os.path.join(out_dir, "result.json")
    md_path = os.path.join(out_dir, "report.md")
    with open(json_path, "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    with open(md_path, "w") as fh:
        fh.write(build_markdown(result))
    return {"json": json_path, "md": md_path}
