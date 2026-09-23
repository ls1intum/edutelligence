"""Render the gateway concurrency benchmark result as JSON + Markdown.

Informational only — no PASS/FAIL gate. There is no baseline yet to set a
threshold against; see the PR description for why blocking was deferred.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


def _ms(v: float) -> str:
    return f"{v:,.1f}"


def build_markdown(result: Dict[str, Any]) -> str:
    lines: List[str] = ["# Gateway Concurrency Benchmark", ""]
    lines.append(f"Run at {result.get('generated_at', 'n/a')} against `{result['env']['gateway_url']}`.")
    lines.append("")

    # -- concurrency ramp --------------------------------------------------
    conc = result.get("concurrency")
    if conc:
        ceiling = conc["configured_ceiling"]
        lines.append("## Concurrency ramp")
        lines.append("")
        onset = conc["onset_concurrency"]
        onset_str = str(onset) if onset is not None else "not reached within the tested steps"
        lines.append(
            f"Onset of failures (>{conc['fail_threshold']:.0%} of a step): **{onset_str}** concurrent streams. "
            f"Configured ceiling: `max-size`={ceiling['spring_task_execution_pool_max_size']} + "
            f"`queue-capacity`={ceiling['spring_task_execution_pool_queue_capacity']} "
            f"(≈{ceiling['approx_admission_ceiling']})."
        )
        lines.append("")
        lines.append("| Concurrency | OK | Failed | Fail rate | TTFB p50 | TTFB p95 | Total p50 |")
        lines.append("|---:|---:|---:|---:|---:|---:|---:|")
        for step in conc["steps"]:
            lines.append(
                f"| {step['concurrency']} | {step['ok']} | {step['failed']} | {step['fail_rate']:.1%} | "
                f"{_ms(step['ttfb_ms'].get('p50_ms', 0))} ms | {_ms(step['ttfb_ms'].get('p95_ms', 0))} ms | "
                f"{_ms(step['total_ms'].get('p50_ms', 0))} ms |"
            )
        lines.append("")

    # -- added latency -------------------------------------------------------
    lat = result.get("latency")
    if lat:
        ov = lat["overhead"]
        lines.append("## Added latency (gateway vs. direct-to-upstream)")
        lines.append("")
        lines.append(
            f"Overhead p50 = **{_ms(ov['overhead_p50_ms'])} ms**, p95 = **{_ms(ov['overhead_p95_ms'])} ms** "
            f"(n={ov['n_gateway']} gateway / {ov['n_direct']} direct)."
        )
        lines.append("")
        lines.append("| Path | p50 | p95 | p99 |")
        lines.append("|---|---:|---:|---:|")
        for label, key in (("Via gateway", "gateway"), ("Direct to fake upstream", "direct")):
            s = lat[key]
            if s.get("n", 0):
                lines.append(f"| {label} | {_ms(s['p50_ms'])} ms | {_ms(s['p95_ms'])} ms | {_ms(s['p99_ms'])} ms |")
        if lat["n_failures"]:
            lines.append("")
            lines.append(f"⚠️ {lat['n_failures']} request(s) failed during this leg (see `result.json`).")
        lines.append("")

    # -- failover --------------------------------------------------------
    fo = result.get("failover")
    if fo is None:
        lines.append("## Failover under load")
        lines.append("")
        lines.append("_Skipped — fewer than 2 `logos-webservice` replicas were running._")
        lines.append("")
    elif fo.get("skipped"):
        lines.append("## Failover under load")
        lines.append("")
        lines.append(f"_Skipped — {fo['reason']}_")
        lines.append("")
    else:
        icon = "✅" if fo["no_visible_impact"] else "❌"
        lines.append("## Failover under load")
        lines.append("")
        lines.append(
            f"**{icon}** killed `{fo['killed_container']}` at t={fo['kill_after_s']}s into a "
            f"{fo['duration_s']}s run with {fo['concurrency']} concurrent streams. "
            f"total={fo['total']}, ok={fo['ok']}, "
            f"**connectivity failures={fo['connectivity_failures']}** (connection error/timeout/5xx), "
            f"other failures={fo['other_failures']}, max latency={_ms(fo['max_total_ms'])} ms."
        )
        if fo["connectivity_failures"]:
            lines.append("")
            lines.append(f"Sample errors: `{fo['connectivity_failure_samples']}`")
        lines.append("")

    lines.append("## Method")
    lines.append("")
    lines.append(
        "- Upstream: `fake_cloud_upstream.py`, an OpenAI-shaped mock (streaming SSE + non-streaming), "
        "so the numbers above are the gateway's own overhead/limits, not a real cloud provider's throttling."
    )
    lines.append(
        "- No PASS/FAIL gate: this is the first version of this benchmark, so there is no baseline yet "
        "to set a threshold against. See the PR description."
    )
    lines.append(f"- Env: `{json.dumps(result.get('env', {}), sort_keys=True)}`")
    lines.append("")
    return "\n".join(lines)


def write_reports(result: Dict[str, Any], out_dir: str) -> Dict[str, str]:
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
