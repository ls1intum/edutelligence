"""Render the benchmark result as JSON + Markdown.

The Markdown report is the human-facing artifact: it carries the verdict
against the 1 ms goal, the phase table (ns detail), and the run metadata.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

# Goal from issue #980: total forwarding overhead < 1 ms per request.
GOAL_NS = 1_000_000
# CI tolerance for the blocking check (shared runner noise); between GOAL_NS
# and this the job passes but the comment warns.
FAIL_NS = 1_500_000


def ns_to_us(ns: float) -> str:
    return f"{ns / 1000.0:,.1f}"


def verdict(overhead_ns: float) -> str:
    if overhead_ns <= GOAL_NS:
        return "PASS"
    if overhead_ns <= FAIL_NS:
        return "WARN"
    return "FAIL"


def build_markdown(result: Dict[str, Any]) -> str:
    """Render the full result dict (as produced by run_benchmark) to Markdown."""
    ov = result["overhead"]
    verdict_str = verdict(ov["overhead_ns"])
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[verdict_str]
    phases = result.get("phases", {})

    lines: List[str] = []
    lines.append("# Per-Request Forwarding Overhead")
    lines.append("")
    lines.append(
        f"**{icon} {verdict_str}** — overhead p50 = **{ns_to_us(ov['overhead_ns'])} µs** "
        f"(goal < {ns_to_us(GOAL_NS)} µs, CI fail threshold {ns_to_us(FAIL_NS)} µs)"
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
        "- Overhead = median(via Logos) − median(direct baseline to the same mock lane), "
        "interleaved blocks to cancel common-mode drift."
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
