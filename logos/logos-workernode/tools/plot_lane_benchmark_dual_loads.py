#!/usr/bin/env python3
"""
Render a dual-panel SVG chart for lane benchmark throughput.

Each panel shows one load profile:
  - varied_unique_prefix (cache-hostile)
  - fixed_shared_prefix (cache-friendly)

Every point is labeled with:
  tok/s and peak GPU memory (GB)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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

RUN_ORDER = [
    "vllm_prefix_off",
    "vllm_prefix_on",
    "ollama_np2",
    "ollama_np4",
    "ollama_np8",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render dual-load throughput SVG with memory annotations."
    )
    parser.add_argument("--varied", required=True, help="lane_benchmark JSON for varied_unique_prefix")
    parser.add_argument("--fixed", required=True, help="lane_benchmark JSON for fixed_shared_prefix")
    parser.add_argument("--output", help="Optional output SVG path")
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


def collect_concurrency(rows_by_run: dict[str, list[dict[str, Any]]]) -> list[int]:
    for run_label in RUN_ORDER:
        rows = rows_by_run.get(run_label)
        if rows:
            return [int(row["concurrency"]) for row in rows]
    return []


def max_tok_s(*rows_maps: dict[str, list[dict[str, Any]]]) -> float:
    vals: list[float] = []
    for rows_by_run in rows_maps:
        for run_label in RUN_ORDER:
            for row in rows_by_run.get(run_label, []):
                val = row.get("aggregate_tok_s")
                if isinstance(val, (int, float)):
                    vals.append(float(val))
    if not vals:
        return 10.0
    return max(10.0, max(vals) * 1.12)


def make_panel_svg(
    *,
    panel_x: int,
    panel_y: int,
    panel_w: int,
    panel_h: int,
    title: str,
    rows_by_run: dict[str, list[dict[str, Any]]],
    y_max: float,
) -> str:
    left = panel_x + 80
    right = panel_x + panel_w - 28
    top = panel_y + 48
    bottom = panel_y + panel_h - 62
    chart_w = right - left
    chart_h = bottom - top

    conc = collect_concurrency(rows_by_run)
    if not conc:
        return f'<text x="{panel_x + 16}" y="{panel_y + 32}" font-size="14" fill="#b91c1c">No data for {esc(title)}</text>'

    def x_to_px(x: int) -> float:
        if len(conc) == 1:
            return left + chart_w / 2
        idx = conc.index(x)
        return left + (idx / (len(conc) - 1)) * chart_w

    def y_to_px(y: float) -> float:
        return top + chart_h - (y / y_max) * chart_h

    parts: list[str] = []
    parts.append(
        f'<rect x="{panel_x}" y="{panel_y}" width="{panel_w}" height="{panel_h}" '
        f'rx="14" fill="#ffffff" stroke="#dbe5f4"/>'
    )
    parts.append(
        f'<text x="{panel_x + 18}" y="{panel_y + 30}" font-family="ui-monospace, Menlo, Consolas, monospace" '
        f'font-size="17" fill="#0f172a">{esc(title)}</text>'
    )

    # Y grid + labels
    ticks = 6
    for i in range(ticks + 1):
        y_val = (y_max / ticks) * i
        y = y_to_px(y_val)
        parts.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{right}" y2="{y:.2f}" stroke="#eef3fb" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 10}" y="{y + 4:.2f}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="12" text-anchor="end" fill="#475569">{y_val:.0f}</text>'
        )

    # X grid + labels
    for x in conc:
        px = x_to_px(x)
        parts.append(
            f'<line x1="{px:.2f}" y1="{top}" x2="{px:.2f}" y2="{bottom}" stroke="#f5f8fc" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{px:.2f}" y="{bottom + 24}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="12" text-anchor="middle" fill="#334155">{x}</text>'
        )

    parts.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#0f172a" stroke-width="1.8"/>')
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#0f172a" stroke-width="1.8"/>')

    label_y_offsets = {
        "vllm_prefix_off": -14,
        "vllm_prefix_on": 14,
        "ollama_np2": -18,
        "ollama_np4": 16,
        "ollama_np8": 30,
    }

    for run_label in RUN_ORDER:
        rows = rows_by_run.get(run_label)
        if not rows:
            continue
        color = COLOR_MAP[run_label]
        pts = " ".join(
            f"{x_to_px(int(row['concurrency'])):.2f},{y_to_px(float(row['aggregate_tok_s'])):.2f}"
            for row in rows
        )
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="3.5"/>')

        for row in rows:
            cx = x_to_px(int(row["concurrency"]))
            cy = y_to_px(float(row["aggregate_tok_s"]))
            mem_label = to_gb_str(row.get("gpu_mem_peak_total_mb"))
            point_label = f"{float(row['aggregate_tok_s']):.1f} | {mem_label}"
            y_offset = label_y_offsets.get(run_label, -12)
            parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="4.4" fill="{color}" stroke="#ffffff" stroke-width="1.3"/>')
            parts.append(
                f'<text x="{cx + 7:.2f}" y="{cy + y_offset:.2f}" '
                f'font-family="ui-monospace, Menlo, Consolas, monospace" font-size="10.5" '
                f'fill="{color}">{esc(point_label)}</text>'
            )

    parts.append(
        f'<text x="{left + chart_w / 2:.2f}" y="{panel_y + panel_h - 16}" '
        f'font-family="ui-monospace, Menlo, Consolas, monospace" font-size="12.5" text-anchor="middle" fill="#0f172a">'
        "Concurrency</text>"
    )
    parts.append(
        f'<text x="{panel_x + 20}" y="{top + chart_h / 2:.2f}" '
        f'font-family="ui-monospace, Menlo, Consolas, monospace" font-size="12.5" text-anchor="middle" '
        f'transform="rotate(-90 {panel_x + 20},{top + chart_h / 2:.2f})" fill="#0f172a">'
        "Aggregate tok/s</text>"
    )
    return "\n".join(parts)


def render_svg(
    varied_payload: dict[str, Any],
    fixed_payload: dict[str, Any],
) -> str:
    varied_rows = index_rows(varied_payload)
    fixed_rows = index_rows(fixed_payload)
    y_max = max_tok_s(varied_rows, fixed_rows)

    width = 1780
    height = 980
    panel_w = 840
    panel_h = 820
    left_panel_x = 50
    right_panel_x = 890
    panel_y = 118

    legend_items = []
    lx = 70
    ly = 74
    for run_label in RUN_ORDER:
        color = COLOR_MAP[run_label]
        name = LABEL_MAP[run_label]
        legend_items.append(
            f'<line x1="{lx}" y1="{ly}" x2="{lx + 28}" y2="{ly}" stroke="{color}" stroke-width="4"/>'
            f'<text x="{lx + 36}" y="{ly + 4}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="14" fill="#0f172a">{esc(name)}</text>'
        )
        lx += 325

    meta = (
        f"varied={Path(str(varied_payload.get('source_file', 'unknown'))).name} | "
        f"fixed={Path(str(fixed_payload.get('source_file', 'unknown'))).name}"
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#f8fbff"/>
      <stop offset="100%" stop-color="#f3f7ff"/>
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="{width}" height="{height}" fill="url(#bg)"/>

  <text x="52" y="40" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="28" fill="#0f172a">
    Qwen2.5-Coder Throughput by Load Type (tok/s | peak GPU memory)
  </text>
  <text x="52" y="62" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="13" fill="#475569">
    {esc(meta)}
  </text>
  {''.join(legend_items)}

  {make_panel_svg(panel_x=left_panel_x, panel_y=panel_y, panel_w=panel_w, panel_h=panel_h, title="Load: varied_unique_prefix (cache-hostile)", rows_by_run=varied_rows, y_max=y_max)}
  {make_panel_svg(panel_x=right_panel_x, panel_y=panel_y, panel_w=panel_w, panel_h=panel_h, title="Load: fixed_shared_prefix (cache-friendly)", rows_by_run=fixed_rows, y_max=y_max)}

  <text x="52" y="{height - 18}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="12" fill="#64748b">
    Point label format: throughput tok/s | peak total GPU memory (GiB)
  </text>
</svg>
"""


def main() -> int:
    args = parse_args()
    varied_path = Path(args.varied)
    fixed_path = Path(args.fixed)

    varied_payload = json.loads(varied_path.read_text())
    fixed_payload = json.loads(fixed_path.read_text())
    varied_payload["source_file"] = str(varied_path)
    fixed_payload["source_file"] = str(fixed_path)

    out_path = Path(args.output) if args.output else varied_path.with_name(
        f"{varied_path.stem}_vs_{fixed_path.stem}_toks_mem.svg"
    )
    out_path.write_text(render_svg(varied_payload, fixed_payload))
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
