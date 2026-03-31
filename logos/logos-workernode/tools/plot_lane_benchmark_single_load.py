#!/usr/bin/env python3
"""
Render a single-load SVG chart from one lane_benchmark JSON.

Shows all run labels found in the JSON (vLLM prefix modes + Ollama np sweeps)
with per-point labels: tok/s | peak GPU memory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


RUN_ORDER = [
    "vllm_prefix_off",
    "vllm_prefix_on",
    "ollama_np2",
    "ollama_np4",
    "ollama_np8",
]

COLOR_MAP = {
    "vllm_prefix_off": "#0b84f3",
    "vllm_prefix_on": "#00a884",
    "ollama_np2": "#f97316",
    "ollama_np4": "#ef4444",
    "ollama_np8": "#b45309",
}

LABEL_MAP = {
    "vllm_prefix_off": "vLLM prefix OFF",
    "vllm_prefix_on": "vLLM prefix ON",
    "ollama_np2": "Ollama np=2",
    "ollama_np4": "Ollama np=4",
    "ollama_np8": "Ollama np=8",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render single-load throughput SVG with memory labels.")
    parser.add_argument("--input", required=True, help="lane_benchmark_*.json")
    parser.add_argument("--output", help="Output SVG path")
    return parser.parse_args()


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def to_gb_str(mem_mb: Any) -> str:
    if isinstance(mem_mb, (int, float)):
        return f"{float(mem_mb) / 1024.0:.1f}G"
    return "n/a"


def index_rows(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for backend in payload.get("backends", []):
        run_label = backend.get("run_label")
        if not isinstance(run_label, str):
            continue
        rows = list(backend.get("results", []))
        rows = sorted(rows, key=lambda r: int(r.get("concurrency", 0)))
        out[run_label] = rows
    return out


def main() -> int:
    args = parse_args()
    in_path = Path(args.input)
    payload = json.loads(in_path.read_text())
    rows_by_run = index_rows(payload)

    # Determine x-axis from first populated run in preferred order.
    x_vals: list[int] = []
    for run_label in RUN_ORDER:
        rows = rows_by_run.get(run_label)
        if rows:
            x_vals = [int(r["concurrency"]) for r in rows]
            break
    if not x_vals:
        raise SystemExit("No benchmark rows found.")

    y_vals: list[float] = []
    for run_label in RUN_ORDER:
        for row in rows_by_run.get(run_label, []):
            tok_s = row.get("aggregate_tok_s")
            if isinstance(tok_s, (int, float)):
                y_vals.append(float(tok_s))
    if not y_vals:
        raise SystemExit("No throughput values found.")
    y_max = max(10.0, max(y_vals) * 1.12)

    width, height = 1640, 980
    left, right, top, bottom = 120, 50, 130, 110
    chart_w = width - left - right
    chart_h = height - top - bottom

    def x_to_px(x: int) -> float:
        if len(x_vals) == 1:
            return left + chart_w / 2
        idx = x_vals.index(x)
        return left + (idx / (len(x_vals) - 1)) * chart_w

    def y_to_px(y: float) -> float:
        return top + chart_h - (y / y_max) * chart_h

    h_ticks = 6
    grid_parts: list[str] = []
    for i in range(h_ticks + 1):
        y_val = (y_max / h_ticks) * i
        y = y_to_px(y_val)
        grid_parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + chart_w}" y2="{y:.2f}" stroke="#e9eef7" stroke-width="1"/>'
        )
        grid_parts.append(
            f'<text x="{left - 12}" y="{y + 4:.2f}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="12" text-anchor="end" fill="#475569">{y_val:.0f}</text>'
        )
    for x in x_vals:
        px = x_to_px(x)
        grid_parts.append(
            f'<line x1="{px:.2f}" y1="{top}" x2="{px:.2f}" y2="{top + chart_h}" stroke="#f4f7fb" stroke-width="1"/>'
        )
        grid_parts.append(
            f'<text x="{px:.2f}" y="{top + chart_h + 28}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="12" text-anchor="middle" fill="#334155">{x}</text>'
        )

    line_parts: list[str] = []
    label_y_offsets = {
        "vllm_prefix_off": -15,
        "vllm_prefix_on": 14,
        "ollama_np2": -20,
        "ollama_np4": 16,
        "ollama_np8": 30,
    }
    for run_label in RUN_ORDER:
        rows = rows_by_run.get(run_label)
        if not rows:
            continue
        color = COLOR_MAP[run_label]
        points = " ".join(
            f"{x_to_px(int(r['concurrency'])):.2f},{y_to_px(float(r['aggregate_tok_s'])):.2f}"
            for r in rows
        )
        line_parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="3.8"/>')
        for row in rows:
            cx = x_to_px(int(row["concurrency"]))
            cy = y_to_px(float(row["aggregate_tok_s"]))
            mem = to_gb_str(row.get("gpu_mem_peak_total_mb"))
            point_label = f"{float(row['aggregate_tok_s']):.1f} | {mem}"
            y_off = label_y_offsets.get(run_label, -12)
            line_parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4.6" fill="{color}" stroke="#ffffff" stroke-width="1.2"/>')
            line_parts.append(
                f'<text x="{cx + 8:.2f}" y="{cy + y_off:.2f}" font-family="ui-monospace, Menlo, Consolas, monospace" '
                f'font-size="10.8" fill="{color}">{esc(point_label)}</text>'
            )

    legend_x = 120
    legend_y = 82
    legend_parts: list[str] = []
    for run_label in RUN_ORDER:
        if run_label not in rows_by_run:
            continue
        color = COLOR_MAP[run_label]
        label = LABEL_MAP[run_label]
        legend_parts.append(
            f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 28}" y2="{legend_y}" stroke="{color}" stroke-width="4"/>'
            f'<text x="{legend_x + 36}" y="{legend_y + 4}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="14" fill="#0f172a">{esc(label)}</text>'
        )
        legend_x += 280

    prompt_mode = payload.get("prompt_mode", "unknown")
    timestamp = payload.get("timestamp_utc", "")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fbff"/>
      <stop offset="100%" stop-color="#f3f7ff"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="{width}" height="{height}" fill="url(#bg)"/>
  <text x="52" y="42" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="29" fill="#0f172a">
    Throughput by Concurrency ({esc(prompt_mode)})
  </text>
  <text x="52" y="64" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="13" fill="#475569">
    source={esc(in_path.name)} | timestamp_utc={esc(str(timestamp))}
  </text>
  {''.join(legend_parts)}

  {''.join(grid_parts)}
  <line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#0f172a" stroke-width="2"/>
  <line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#0f172a" stroke-width="2"/>

  {''.join(line_parts)}

  <text x="{left + chart_w / 2}" y="{height - 36}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="15" text-anchor="middle" fill="#0f172a">
    Concurrency
  </text>
  <text x="30" y="{top + chart_h / 2}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="15" text-anchor="middle" transform="rotate(-90 30,{top + chart_h / 2})" fill="#0f172a">
    Aggregate throughput (tok/s)
  </text>
  <text x="52" y="{height - 16}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="12" fill="#64748b">
    Point label format: tok/s | peak total GPU memory (GiB)
  </text>
</svg>
"""

    out_path = Path(args.output) if args.output else in_path.with_name(f"{in_path.stem}_toks_mem.svg")
    out_path.write_text(svg)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
