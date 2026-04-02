#!/usr/bin/env python3
"""
Render a simple SVG line chart for lane benchmark throughput.

Usage:
  ./.venv/bin/python plot_lane_benchmark.py \
      --input bench_results/lane_benchmark_YYYYMMDD_HHMMSS.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render throughput comparison SVG from lane benchmark JSON.")
    parser.add_argument("--input", required=True, help="Path to lane_benchmark_*.json")
    parser.add_argument("--output", help="Optional output SVG path")
    return parser.parse_args()


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def pick_rows(payload: dict, backend: str) -> list[dict]:
    for item in payload.get("backends", []):
        if item.get("backend") == backend:
            return item.get("results", [])
    return []


def main() -> int:
    args = parse_args()
    in_path = Path(args.input)
    payload = json.loads(in_path.read_text())

    vllm_rows = sorted(pick_rows(payload, "vllm"), key=lambda r: int(r["concurrency"]))
    ollama_rows = sorted(pick_rows(payload, "ollama"), key=lambda r: int(r["concurrency"]))
    if not vllm_rows or not ollama_rows:
        raise SystemExit("Missing vLLM or Ollama rows in input JSON.")

    x_vals = [int(row["concurrency"]) for row in vllm_rows]
    vllm_vals = [float(row["aggregate_tok_s"]) for row in vllm_rows]
    ollama_vals = [float(row["aggregate_tok_s"]) for row in ollama_rows]
    y_max = max(vllm_vals + ollama_vals)
    y_max = max(10.0, y_max * 1.1)

    width, height = 1080, 680
    left, right, top, bottom = 110, 70, 90, 110
    chart_w = width - left - right
    chart_h = height - top - bottom

    def x_to_px(x: int) -> float:
        if len(x_vals) == 1:
            return left + chart_w / 2
        idx = x_vals.index(x)
        return left + (idx / (len(x_vals) - 1)) * chart_w

    def y_to_px(y: float) -> float:
        return top + chart_h - (y / y_max) * chart_h

    def poly_points(xs: list[int], ys: list[float]) -> str:
        return " ".join(f"{x_to_px(x):.2f},{y_to_px(y):.2f}" for x, y in zip(xs, ys))

    h_ticks = 6
    v_lines = []
    for i in range(h_ticks + 1):
        y_val = (y_max / h_ticks) * i
        y = y_to_px(y_val)
        v_lines.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + chart_w}" y2="{y:.2f}" '
            f'stroke="#e5e7eb" stroke-width="1"/>'
        )
        v_lines.append(
            f'<text x="{left - 12}" y="{y + 5:.2f}" font-family="monospace" font-size="14" '
            f'text-anchor="end" fill="#374151">{y_val:.0f}</text>'
        )

    x_ticks = []
    for x in x_vals:
        px = x_to_px(x)
        x_ticks.append(
            f'<line x1="{px:.2f}" y1="{top}" x2="{px:.2f}" y2="{top + chart_h}" '
            f'stroke="#f3f4f6" stroke-width="1"/>'
        )
        x_ticks.append(
            f'<text x="{px:.2f}" y="{top + chart_h + 34}" font-family="monospace" '
            f'font-size="14" text-anchor="middle" fill="#374151">{x}</text>'
        )

    vllm_color = "#0b84f3"
    ollama_color = "#f97316"
    stamp = esc(payload.get("timestamp_utc", ""))
    title = "Throughput vs Concurrency (vLLM vs Ollama)"
    subtitle = f"source: {in_path.name}  |  timestamp_utc: {stamp}"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>
  <text x="{left}" y="42" font-family="monospace" font-size="28" fill="#111827">{esc(title)}</text>
  <text x="{left}" y="66" font-family="monospace" font-size="13" fill="#6b7280">{esc(subtitle)}</text>

  <g>
    {''.join(v_lines)}
    {''.join(x_ticks)}
    <line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#111827" stroke-width="2"/>
    <line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#111827" stroke-width="2"/>
  </g>

  <polyline points="{poly_points(x_vals, vllm_vals)}" fill="none" stroke="{vllm_color}" stroke-width="4"/>
  <polyline points="{poly_points(x_vals, ollama_vals)}" fill="none" stroke="{ollama_color}" stroke-width="4"/>

  {''.join(f'<circle cx="{x_to_px(x):.2f}" cy="{y_to_px(y):.2f}" r="5" fill="{vllm_color}"/>' for x, y in zip(x_vals, vllm_vals))}
  {''.join(f'<circle cx="{x_to_px(x):.2f}" cy="{y_to_px(y):.2f}" r="5" fill="{ollama_color}"/>' for x, y in zip(x_vals, ollama_vals))}

  <g>
    <rect x="{left + chart_w - 250}" y="{top + 10}" width="240" height="72" fill="#f9fafb" stroke="#e5e7eb"/>
    <line x1="{left + chart_w - 232}" y1="{top + 34}" x2="{left + chart_w - 192}" y2="{top + 34}" stroke="{vllm_color}" stroke-width="4"/>
    <text x="{left + chart_w - 180}" y="{top + 39}" font-family="monospace" font-size="14" fill="#111827">vLLM</text>
    <line x1="{left + chart_w - 232}" y1="{top + 62}" x2="{left + chart_w - 192}" y2="{top + 62}" stroke="{ollama_color}" stroke-width="4"/>
    <text x="{left + chart_w - 180}" y="{top + 67}" font-family="monospace" font-size="14" fill="#111827">Ollama</text>
  </g>

  <text x="{left + chart_w / 2}" y="{height - 34}" font-family="monospace" font-size="16" text-anchor="middle" fill="#111827">Concurrency</text>
  <text x="26" y="{top + chart_h / 2}" font-family="monospace" font-size="16" text-anchor="middle" transform="rotate(-90 26,{top + chart_h / 2})" fill="#111827">Aggregate throughput (tok/s)</text>
</svg>
"""

    out_path = Path(args.output) if args.output else in_path.with_name(f"{in_path.stem}_throughput.svg")
    out_path.write_text(svg)
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
