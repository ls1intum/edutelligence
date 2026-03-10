#!/usr/bin/env python3
"""
Render a throughput line chart for Ollama num_parallel sweep results.

Usage:
  ./.venv/bin/python plot_ollama_parallel_sweep.py \
      --input bench_results/ollama_parallel_sweep_YYYYMMDD_HHMMSS.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render SVG chart from ollama_parallel_sweep JSON.")
    parser.add_argument("--input", required=True, help="Path to ollama_parallel_sweep_*.json")
    parser.add_argument("--output", help="Optional output SVG path")
    return parser.parse_args()


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def to_gib_str(mem_rows: list[dict]) -> str:
    if not mem_rows:
        return "n/a"
    parts = []
    for row in mem_rows:
        idx = int(row.get("index", -1))
        used = float(row.get("used_mb", 0.0))
        total = float(row.get("total_mb", 1.0))
        parts.append(f"GPU{idx}:{used/1024:.1f}/{total/1024:.1f}GiB")
    return " ".join(parts)


def series_from_payload(payload: dict) -> list[dict]:
    out: list[dict] = []
    for item in payload.get("sweep", []):
        bench = item.get("benchmark", {})
        rows = bench.get("results", [])
        points = []
        for row in rows:
            conc = int(row.get("concurrency", 0))
            tok = row.get("aggregate_tok_s")
            val = float(tok) if tok is not None else None
            points.append((conc, val))
        out.append({
            "target": int(item.get("target_num_parallel", 0)),
            "effective": int(item.get("effective_num_parallel", 0)),
            "saturated": bool(item.get("saturated", False)),
            "saturation_reason": str(item.get("saturation_reason", "")),
            "peak_mem": bench.get("gpu_memory_peak_mb", []),
            "points": points,
        })
    out.sort(key=lambda s: s["target"])
    return out


def main() -> int:
    args = parse_args()
    in_path = Path(args.input)
    payload = json.loads(in_path.read_text())
    series = series_from_payload(payload)
    if not series:
        raise SystemExit("No sweep series in input JSON.")

    x_vals = sorted({conc for s in series for conc, _ in s["points"]})
    y_vals = [
        val for s in series for _, val in s["points"]
        if val is not None
    ]
    if not x_vals or not y_vals:
        raise SystemExit("No numeric points found in input JSON.")

    y_max = max(y_vals)
    y_max = max(10.0, y_max * 1.2)

    width, height = 1280, 760
    left, right, top, bottom = 120, 120, 100, 130
    chart_w = width - left - right
    chart_h = height - top - bottom

    def x_to_px(x: int) -> float:
        if len(x_vals) == 1:
            return left + chart_w / 2
        idx = x_vals.index(x)
        return left + (idx / (len(x_vals) - 1)) * chart_w

    def y_to_px(y: float) -> float:
        return top + chart_h - (y / y_max) * chart_h

    y_ticks = 7
    grid_lines = []
    for i in range(y_ticks + 1):
        y_val = (y_max / y_ticks) * i
        y_px = y_to_px(y_val)
        grid_lines.append(
            f'<line x1="{left}" y1="{y_px:.2f}" x2="{left + chart_w}" y2="{y_px:.2f}" '
            f'stroke="#e5e7eb" stroke-width="1"/>'
        )
        grid_lines.append(
            f'<text x="{left - 14}" y="{y_px + 5:.2f}" font-family="monospace" font-size="14" '
            f'text-anchor="end" fill="#374151">{y_val:.0f}</text>'
        )

    x_grid = []
    for x in x_vals:
        x_px = x_to_px(x)
        x_grid.append(
            f'<line x1="{x_px:.2f}" y1="{top}" x2="{x_px:.2f}" y2="{top + chart_h}" '
            f'stroke="#f3f4f6" stroke-width="1"/>'
        )
        x_grid.append(
            f'<text x="{x_px:.2f}" y="{top + chart_h + 36}" font-family="monospace" '
            f'font-size="14" text-anchor="middle" fill="#374151">{x}</text>'
        )

    palette = [
        "#0b84f3",
        "#16a34a",
        "#f97316",
        "#a855f7",
        "#db2777",
        "#0891b2",
    ]
    axis_color = "#111827"
    sat_color = "#dc2626"

    line_svg: list[str] = []
    point_svg: list[str] = []
    sat_svg: list[str] = []
    legend_svg: list[str] = []

    legend_x = left + chart_w - 390
    legend_y = top + 16
    legend_h = 30 + (len(series) * 26)
    legend_svg.append(
        f'<rect x="{legend_x}" y="{legend_y}" width="370" height="{legend_h}" '
        f'fill="#f9fafb" stroke="#e5e7eb"/>'
    )

    for idx, s in enumerate(series):
        color = palette[idx % len(palette)]
        points = [(c, v) for c, v in s["points"] if v is not None]
        if not points:
            continue

        poly = " ".join(f"{x_to_px(c):.2f},{y_to_px(float(v)):.2f}" for c, v in points)
        line_svg.append(
            f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="3.5"/>'
        )
        for c, v in points:
            point_svg.append(
                f'<circle cx="{x_to_px(c):.2f}" cy="{y_to_px(float(v)):.2f}" r="4.2" fill="{color}"/>'
            )

        label = f"target {s['target']} -> eff {s['effective']}"
        if s["saturated"]:
            label += "  [MEM SAT]"

        ly = legend_y + 24 + (idx * 26)
        legend_svg.append(
            f'<line x1="{legend_x + 14}" y1="{ly - 5}" x2="{legend_x + 52}" y2="{ly - 5}" '
            f'stroke="{color}" stroke-width="4"/>'
        )
        legend_svg.append(
            f'<text x="{legend_x + 60}" y="{ly}" font-family="monospace" font-size="13" fill="#111827">{esc(label)}</text>'
        )

        if s["saturated"]:
            last_c, last_v = points[-1]
            px = x_to_px(last_c)
            py = y_to_px(float(last_v))
            tri = (
                f"{px:.2f},{py - 12:.2f} "
                f"{px - 9:.2f},{py + 6:.2f} "
                f"{px + 9:.2f},{py + 6:.2f}"
            )
            sat_svg.append(f'<polygon points="{tri}" fill="{sat_color}"/>')
            sat_svg.append(
                f'<text x="{px + 12:.2f}" y="{py - 14:.2f}" font-family="monospace" font-size="12" '
                f'fill="{sat_color}">mem sat: target {s["target"]} → eff {s["effective"]}</text>'
            )

    mem_lines = []
    for i, s in enumerate(series):
        mem_txt = to_gib_str(s["peak_mem"])
        mem_lines.append(
            f'<text x="{left}" y="{height - 64 + (i * 18)}" font-family="monospace" font-size="12" '
            f'fill="#4b5563">target {s["target"]} -> eff {s["effective"]}: peak {esc(mem_txt)}</text>'
        )

    stamp = esc(payload.get("timestamp_utc", ""))
    model = esc(str(payload.get("model", "")))
    context = int(payload.get("context_length", 0))
    title = "Ollama Throughput vs Concurrency by num_parallel"
    subtitle = (
        f"model: {model} | fixed context_length={context} | "
        f"source: {in_path.name} | timestamp_utc: {stamp}"
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>
  <text x="{left}" y="44" font-family="monospace" font-size="30" fill="#111827">{esc(title)}</text>
  <text x="{left}" y="70" font-family="monospace" font-size="13" fill="#6b7280">{esc(subtitle)}</text>

  <g>
    {''.join(grid_lines)}
    {''.join(x_grid)}
    <line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="{axis_color}" stroke-width="2"/>
    <line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="{axis_color}" stroke-width="2"/>
  </g>

  {''.join(line_svg)}
  {''.join(point_svg)}
  {''.join(sat_svg)}
  {''.join(legend_svg)}

  <text x="{left + chart_w / 2}" y="{height - 20}" font-family="monospace" font-size="16" text-anchor="middle" fill="#111827">Concurrency</text>
  <text x="28" y="{top + chart_h / 2}" font-family="monospace" font-size="16" text-anchor="middle" transform="rotate(-90 28,{top + chart_h / 2})" fill="#111827">Aggregate throughput (tok/s)</text>

  {''.join(mem_lines)}
</svg>
"""

    out_path = Path(args.output) if args.output else in_path.with_name(f"{in_path.stem}_throughput.svg")
    out_path.write_text(svg)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
