"""Render the gateway concurrency benchmark result as JSON + Markdown.

Informational only — no PASS/FAIL gate. There is no baseline yet to set a
threshold against; see the PR description for why blocking was deferred.
The budget-admission section only flags an optional p99 threshold.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


def _ms(v: float) -> str:
    return f"{v:,.1f}"


def _db_cell(snap: Dict[str, Any]) -> str:
    if not snap or snap.get("query_ms") is None:
        return "n/a"
    backlog = snap.get("unfinalized_rows")
    backlog_str = f", {backlog:,} unpriced rows" if backlog is not None else ""
    return f"{_ms(snap['query_ms'])} ms{backlog_str}"


def _budget_section(bud: Dict[str, Any]) -> List[str]:
    lines: List[str] = ["## Budget admission", ""]
    if bud.get("skipped"):
        lines.append(f"_Skipped — {bud.get('reason', 'n/a')}_")
        lines.append("")
        return lines
    load = bud.get("load", {})
    base = bud.get("baseline", {})
    thr = bud.get("threshold", {})
    in_logos = bud.get("in_logos", {})
    logos = in_logos.get("logos", {})

    def _flag(label: str, key: str) -> str:
        limit = thr.get(f"{key}_max_ms")
        if limit is None:
            return ""
        if not logos or thr.get(f"{key}_exceeded"):
            return f" ❌ {label} above the {_ms(limit)} ms threshold" if logos else " ❌ not measured"
        return f" ✅ {label} within the {_ms(limit)} ms threshold"

    logos_str = (
        f"Time in Logos median = **{_ms(logos['p50_ms'])} ms**{_flag('median', 'p50')}, "
        f"p99 = **{_ms(logos['p99_ms'])} ms**{_flag('p99', 'p99')}."
        if logos
        else f"Time in Logos: not measured ({in_logos.get('error', 'no rows')}){_flag('', 'p99')}."
    )
    lines.append(
        f"Application key **with** a budget limit and a month of history (`seed_budget.sql`), "
        f"{bud['concurrency']} concurrent workers for {bud['duration_s']} s "
        f"(budget cache TTL {bud['cache_ttl_s']} s, so the load spans at least one refresh). "
        f"{bud['requests']} requests, {bud['failed']} failed, **{bud['n_5xx']} HTTP 5xx**. "
        f"{logos_str}"
    )
    lines.append("")
    lines.append("| Phase | n | p50 | p95 | p99 | max |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for label, s in (("Idle baseline (sequential)", base), ("Under load", load)):
        if s.get("n", 0):
            lines.append(
                f"| {label} | {s['n']} | {_ms(s['p50_ms'])} ms | {_ms(s['p95_ms'])} ms | "
                f"{_ms(s['p99_ms'])} ms | {_ms(s['max_ms'])} ms |"
            )
    if logos:
        lines.append(
            f"| Time in Logos, per request of the load | {in_logos['n']} | {_ms(logos['p50_ms'])} ms | "
            f"{_ms(logos['p95_ms'])} ms | {_ms(logos['p99_ms'])} ms | {_ms(logos['max_ms'])} ms |"
        )
        for key, label in (
            ("admission", "… admission (auth, rate limit, budget, reservation)"),
            ("call", "… call (admission end to the provider call)"),
            ("tail", "… tail (provider response to end of the response: delivery, settle)"),
        ):
            part = in_logos.get(key, {})
            if part:
                lines.append(
                    f"| {label} | {in_logos['n']} | {_ms(part['p50_ms'])} ms | {_ms(part['p95_ms'])} ms | "
                    f"{_ms(part['p99_ms'])} ms | {_ms(part['max_ms'])} ms |"
                )
    lines.append("")
    lines.append(
        "_Time in Logos_ is read back from each request's `log_entry` row: arrival at the controller to the "
        "end of the response, minus the provider window. It is the gateway's own cost without the fake "
        "upstream's fixed delay and without the hop through Traefik; the two phase rows above it include both."
    )
    lines.append("")
    lines.append(
        f"Budget refresh query in the database (`apiKeyBudgetUsage`): before the load "
        f"{_db_cell(bud.get('db_before', {}))}; after {_db_cell(bud.get('db_after', {}))}."
    )
    lines.append("")
    windows = bud.get("windows", [])
    if windows:
        lines.append(f"Latency by send time ({bud.get('window_s', 5)} s windows):")
        lines.append("")
        lines.append("| From | Requests | Failed | p50 | p95 | max |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        for w in windows:
            lines.append(
                f"| {w['start_s']} s | {w['requests']} | {w['failed']} | {_ms(w['p50_ms'])} ms | "
                f"{_ms(w['p95_ms'])} ms | {_ms(w['max_ms'])} ms |"
            )
        lines.append("")
    lines.append(
        "A refresh that re-prices the key's month blocks every request of the key that misses the "
        "cache, so a slow refresh shows up as a window whose requests all finish late together, and "
        "as 5xx once the long queries hold the connections that authentication needs."
    )
    if bud.get("status_counts"):
        lines.append("")
        lines.append(f"Status counts: `{json.dumps(bud['status_counts'], sort_keys=True)}`")
    if bud.get("failure_samples"):
        lines.append("")
        lines.append(f"Sample errors: `{bud['failure_samples'][:3]}`")
    lines.append("")
    return lines


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
            f"Peak gateway relay tasks simultaneously: **{conc.get('max_concurrent_relays', 0)}**. "
            f"Onset of failures (>{conc['fail_threshold']:.0%} of a step): **{onset_str}** requests per step. "
            f"Configured ceiling: `max-size`={ceiling['spring_task_execution_pool_max_size']} + "
            f"`queue-capacity`={ceiling['spring_task_execution_pool_queue_capacity']} "
            f"(≈{ceiling['approx_admission_ceiling_per_replica']} per replica) "
            f"x {ceiling['replicas']} replica(s) = ≈{ceiling['approx_admission_ceiling']}."
        )
        lines.append("")
        lines.append(
            "| Step size | Peak relayed | OK | Failed | Truncated | Fail rate | TTFB p50 | TTFB p95 | Total p50 |"
        )
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for step in conc["steps"]:
            peak = step.get("peak_concurrent_relays", 0)
            peak_cell = f"{peak} ⚠️" if step.get("hold_timed_out") else str(peak)
            lines.append(
                f"| {step['concurrency']} | {peak_cell} | {step['ok']} | {step['failed']} | "
                f"{step.get('truncated_streams', 0)} | {step['fail_rate']:.1%} | "
                f"{_ms(step['ttfb_ms'].get('p50_ms', 0))} ms | {_ms(step['ttfb_ms'].get('p95_ms', 0))} ms | "
                f"{_ms(step['total_ms'].get('p50_ms', 0))} ms |"
            )
        lines.append("")
        lines.append(
            "_Step size_ is how many requests were fired at once; _peak relayed_ is how many "
            "``StreamingResponseBody`` tasks the webservice replicas had open at the same moment, "
            "counted around the gateway relay task itself (sum of per-replica peaks). The fake "
            "upstream only pins each completion open until that peak is sampled — counting overlap "
            "there would over-count, because the gateway opens the upstream response before the "
            "executor task runs. ⚠️ marks a step that never became fully concurrent within the "
            f"{conc.get('hold_timeout_s', 0):.0f}s hold budget — which is what reaching the ceiling "
            "looks like. _Truncated_ counts 2xx streams that ended without the terminal SSE "
            "event; they are failures. Latencies here are measured under the barrier and include "
            "waiting for a held slot, so read them as behaviour under load, not as the gateway's "
            "latency — that is the added-latency section below."
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
            f"**connectivity failures={fo['connectivity_failures']}** (connection error/timeout/5xx, "
            f"incl. {fo.get('truncated_streams', 0)} truncated stream(s)), "
            f"other failures={fo['other_failures']}, max latency={_ms(fo['max_total_ms'])} ms."
        )
        if fo["connectivity_failures"]:
            lines.append("")
            lines.append(f"Sample errors: `{fo['connectivity_failure_samples']}`")
        lines.append("")

    # -- budget admission ------------------------------------------------
    bud = result.get("budget")
    if bud is not None:
        lines.extend(_budget_section(bud))

    lines.append("## Method")
    lines.append("")
    lines.append(
        "- Upstream: `fake_cloud_upstream.py`, an OpenAI-shaped mock (streaming SSE + non-streaming), "
        "so the numbers above are the gateway's own overhead/limits, not a real cloud provider's throttling."
    )
    lines.append(
        "- The concurrency, latency and failover legs have no PASS/FAIL gate yet. The budget-admission leg "
        "checks the median and p99 time in Logos against `LOGOS_BENCH_GW_BUDGET_LOGOS_P50_MAX_MS` and "
        "`LOGOS_BENCH_GW_BUDGET_LOGOS_P99_MAX_MS`; with `LOGOS_BENCH_GW_BUDGET_FAIL_ON_THRESHOLD=1` "
        "a breach fails the run."
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
