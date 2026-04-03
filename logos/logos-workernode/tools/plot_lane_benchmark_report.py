#!/usr/bin/env python3
"""
Generate presentation-ready SVG artifacts from lane benchmark JSONs:
  1) clear throughput+latency chart for varied load
  2) clear throughput+latency chart for fixed load
  3) styled summary table with highlighted findings
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PALETTE = [
    "#0057E7",  # blue
    "#00A676",  # green
    "#FF7F11",  # orange
    "#D7263D",  # red
    "#7F3C8D",  # purple
    "#6B7280",  # gray
]

LABEL_OVERRIDES = {
    "vllm_prefix_off": "vLLM prefix OFF",
    "vllm_prefix_on": "vLLM prefix ON",
    "ollama_np1": "Ollama np=1",
    "ollama_np2": "Ollama np=2",
    "ollama_np4": "Ollama np=4",
    "ollama_np8": "Ollama np=8",
    "ollama_np16": "Ollama np=16",
    "ollama_np32": "Ollama np=32",
}

PREFERRED_ORDER = [
    "vllm_prefix_off",
    "vllm_prefix_on",
    "ollama_np1",
    "ollama_np2",
    "ollama_np4",
    "ollama_np8",
    "ollama_np16",
    "ollama_np32",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate clear charts + summary table from lane benchmark JSONs.")
    parser.add_argument("--varied", required=True, help="lane_benchmark json (varied_unique_prefix)")
    parser.add_argument("--fixed", required=True, help="lane_benchmark json (fixed_shared_prefix)")
    parser.add_argument("--output-dir", default="bench_results")
    parser.add_argument(
        "--output-prefix",
        default="qwen_coder",
        help="Prefix used for output SVG filenames.",
    )
    parser.add_argument(
        "--benchmark-title",
        default="Qwen2.5-Coder",
        help="Benchmark title shown in charts and summary table.",
    )
    return parser.parse_args()


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def run_display_name(run_label: str) -> str:
    return LABEL_OVERRIDES.get(run_label, run_label)


def ordered_labels(labels: list[str]) -> list[str]:
    seen = set(labels)
    out: list[str] = [label for label in PREFERRED_ORDER if label in seen]
    out.extend(sorted(label for label in labels if label not in set(out)))
    return out


def color_map(labels: list[str]) -> dict[str, str]:
    return {label: PALETTE[i % len(PALETTE)] for i, label in enumerate(labels)}


def load_rows(path: Path) -> tuple[dict[str, list[dict[str, Any]]], list[int], str]:
    payload = json.loads(path.read_text())
    rows_by_run: dict[str, list[dict[str, Any]]] = {}
    for backend in payload.get("backends", []):
        run_label = backend.get("run_label")
        if not isinstance(run_label, str):
            continue
        rows = list(backend.get("results", []))
        rows.sort(key=lambda r: int(r.get("concurrency", 0)))
        rows_by_run[run_label] = rows

    conc: list[int] = []
    for label in ordered_labels(list(rows_by_run.keys())):
        if rows_by_run[label]:
            conc = [int(r["concurrency"]) for r in rows_by_run[label]]
            break
    prompt_mode = str(payload.get("prompt_mode", "unknown"))
    return rows_by_run, conc, prompt_mode


def text_box(
    x: float,
    y: float,
    text: str,
    *,
    color: str,
    font_size: int = 10,
    pad_x: int = 5,
    pad_y: int = 4,
    corner: int = 5,
) -> str:
    width, height = text_box_dims(text, font_size=font_size, pad_x=pad_x, pad_y=pad_y)
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="{corner}" '
        f'fill="#ffffff" fill-opacity="0.98" stroke="{color}" stroke-width="1.8"/>'
        f'<text x="{x + pad_x:.1f}" y="{y + pad_y + font_size - 1:.1f}" '
        f'font-family="ui-monospace, Menlo, Consolas, monospace" font-size="{font_size}" '
        f'fill="#0b1220" style="paint-order:stroke;stroke:#ffffff;stroke-width:2.4;stroke-linejoin:round;">{esc(text)}</text>'
    )


def text_box_dims(
    text: str,
    *,
    font_size: int = 10,
    pad_x: int = 5,
    pad_y: int = 4,
) -> tuple[float, float]:
    width = max(32, int(len(text) * (font_size * 0.62))) + 2 * pad_x
    height = font_size + 2 * pad_y
    return float(width), float(height)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def distribute_vertical_positions(
    desired_y: list[float],
    *,
    min_y: float,
    max_y: float,
    min_gap: float,
) -> list[float]:
    if not desired_y:
        return []
    if len(desired_y) == 1:
        return [clamp(desired_y[0], min_y, max_y)]

    sorted_idx = sorted(range(len(desired_y)), key=lambda i: desired_y[i])
    usable_span = max(0.0, max_y - min_y)
    effective_gap = min(min_gap, usable_span / max(1, len(desired_y) - 1))

    out = [0.0] * len(desired_y)
    for j, idx in enumerate(sorted_idx):
        y = clamp(desired_y[idx], min_y, max_y)
        if j > 0:
            prev = out[sorted_idx[j - 1]]
            y = max(y, prev + effective_gap)
        out[idx] = y

    overflow = out[sorted_idx[-1]] - max_y
    if overflow > 0:
        for idx in sorted_idx:
            out[idx] -= overflow

    if out[sorted_idx[0]] < min_y:
        shift = min_y - out[sorted_idx[0]]
        for idx in sorted_idx:
            out[idx] += shift
    return out


def text_box_with_leader(
    box_x: float,
    box_y: float,
    text: str,
    *,
    color: str,
    anchor_x: float,
    anchor_y: float,
    font_size: int = 10,
    pad_x: int = 5,
    pad_y: int = 4,
) -> str:
    width, height = text_box_dims(text, font_size=font_size, pad_x=pad_x, pad_y=pad_y)
    edge_x = box_x if anchor_x <= box_x else box_x + width
    edge_y = clamp(anchor_y, box_y + 2, box_y + height - 2)
    return (
        f'<line x1="{anchor_x:.1f}" y1="{anchor_y:.1f}" x2="{edge_x:.1f}" y2="{edge_y:.1f}" '
        f'stroke="{color}" stroke-width="1.4" stroke-opacity="0.95"/>'
        + text_box(
            box_x,
            box_y,
            text,
            color=color,
            font_size=font_size,
            pad_x=pad_x,
            pad_y=pad_y,
        )
    )


def draw_combined_chart(
    rows_by_run: dict[str, list[dict[str, Any]]],
    conc: list[int],
    mode_title: str,
    input_name: str,
    benchmark_title: str,
) -> str:
    labels = ordered_labels(list(rows_by_run.keys()))
    colors = color_map(labels)
    if not conc:
        raise ValueError("No concurrency values found")

    width, height = 1780, 1120
    margin = 70
    panel_gap = 50
    panel_h = 420
    panel_w = width - 2 * margin
    top_panel_y = 130
    bottom_panel_y = top_panel_y + panel_h + panel_gap
    right_label_reserve = 280.0

    # Throughput Y max
    tp_vals: list[float] = []
    lt_vals: list[float] = []
    for label in labels:
        for row in rows_by_run[label]:
            tp = row.get("aggregate_tok_s")
            ttft = row.get("avg_ttft_ms")
            p95 = row.get("p95_latency_s")
            if isinstance(tp, (int, float)):
                tp_vals.append(float(tp))
            if isinstance(ttft, (int, float)):
                lt_vals.append(float(ttft))
            if isinstance(p95, (int, float)):
                lt_vals.append(float(p95) * 1000.0)
    tp_max = max(10.0, max(tp_vals) * 1.16 if tp_vals else 10.0)
    lt_max = max(1000.0, max(lt_vals) * 1.16 if lt_vals else 1000.0)

    def panel_bounds(panel_y: int) -> tuple[float, float, float, float]:
        left = margin + 70.0
        right = margin + panel_w - right_label_reserve
        top = panel_y + 24.0
        bottom = panel_y + panel_h - 56.0
        return left, right, top, bottom

    def chart_xy(
        *,
        panel_y: int,
        x: int,
        y: float,
        y_max: float,
    ) -> tuple[float, float]:
        left, right, top, bottom = panel_bounds(panel_y)
        if len(conc) == 1:
            px = (left + right) / 2
        else:
            idx = conc.index(x)
            px = left + (idx / (len(conc) - 1)) * (right - left)
        py = top + (1.0 - (y / y_max)) * (bottom - top)
        return px, py

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
    )
    parts.append(
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#f6fbff"/><stop offset="100%" stop-color="#eef6ff"/>'
        "</linearGradient></defs>"
    )
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="url(#bg)"/>')
    parts.append(
        f'<text x="{margin}" y="44" font-family="ui-monospace, Menlo, Consolas, monospace" '
        f'font-size="30" fill="#0f172a">{esc(benchmark_title)} Benchmark ({esc(mode_title)})</text>'
    )
    parts.append(
        f'<text x="{margin}" y="70" font-family="ui-monospace, Menlo, Consolas, monospace" '
        f'font-size="13" fill="#334155">source: {esc(input_name)} | top panel labels: tok/s | peak GiB</text>'
    )

    # Legend
    lx = margin
    ly = 98
    for label in labels:
        color = colors[label]
        name = run_display_name(label)
        parts.append(
            f'<line x1="{lx}" y1="{ly}" x2="{lx + 30}" y2="{ly}" stroke="{color}" stroke-width="4"/>'
            f'<text x="{lx + 38}" y="{ly + 5}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="14" fill="#0f172a">{esc(name)}</text>'
        )
        lx += 230
    parts.append(
        f'<line x1="{width - 350}" y1="{ly - 8}" x2="{width - 320}" y2="{ly - 8}" stroke="#1f2937" stroke-width="3"/>'
        f'<text x="{width - 315}" y="{ly - 3}" font-family="ui-monospace, Menlo, Consolas, monospace" '
        f'font-size="12" fill="#0f172a">TTFT (ms)</text>'
    )
    parts.append(
        f'<line x1="{width - 350}" y1="{ly + 10}" x2="{width - 320}" y2="{ly + 10}" stroke="#1f2937" stroke-width="3" stroke-dasharray="7 5"/>'
        f'<text x="{width - 315}" y="{ly + 15}" font-family="ui-monospace, Menlo, Consolas, monospace" '
        f'font-size="12" fill="#0f172a">P95 latency (ms)</text>'
    )

    for panel_y, panel_title, y_max, y_axis_label in [
        (top_panel_y, "Throughput", tp_max, "Aggregate tok/s"),
        (bottom_panel_y, "Latency", lt_max, "Milliseconds"),
    ]:
        left, right, top, bottom = panel_bounds(panel_y)
        parts.append(
            f'<rect x="{margin}" y="{panel_y}" width="{panel_w}" height="{panel_h}" rx="16" '
            f'fill="#ffffff" stroke="#c7d7ee" stroke-width="1.2"/>'
        )
        parts.append(
            f'<text x="{margin + 16}" y="{panel_y + 18}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="16" fill="#0f172a">{panel_title}</text>'
        )
        for i in range(7):
            yv = y_max * i / 6.0
            py = top + (1.0 - i / 6.0) * (bottom - top)
            parts.append(f'<line x1="{left}" y1="{py:.1f}" x2="{right}" y2="{py:.1f}" stroke="#e8eff9" stroke-width="1"/>')
            parts.append(
                f'<text x="{left - 10}" y="{py + 4:.1f}" font-family="ui-monospace, Menlo, Consolas, monospace" '
                f'font-size="11" text-anchor="end" fill="#334155">{yv:.0f}</text>'
            )
        for x in conc:
            px, _ = chart_xy(panel_y=panel_y, x=x, y=0.0, y_max=y_max)
            parts.append(f'<line x1="{px:.1f}" y1="{top}" x2="{px:.1f}" y2="{bottom}" stroke="#f2f6fc" stroke-width="1"/>')
            parts.append(
                f'<text x="{px:.1f}" y="{bottom + 25}" font-family="ui-monospace, Menlo, Consolas, monospace" '
                f'font-size="11" text-anchor="middle" fill="#1f2937">{x}</text>'
            )

        parts.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#0f172a" stroke-width="2"/>')
        parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#0f172a" stroke-width="2"/>')
        parts.append(
            f'<text x="{left + (right-left)/2:.1f}" y="{bottom + 44}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="13" text-anchor="middle" fill="#0f172a">Concurrency</text>'
        )
        parts.append(
            f'<text x="{margin + 14}" y="{top + (bottom-top)/2:.1f}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="13" text-anchor="middle" transform="rotate(-90 {margin + 14},{top + (bottom-top)/2:.1f})" fill="#0f172a">{y_axis_label}</text>'
        )

    # Draw lines and labels
    offset_tp = [-18, 14, -24, 18, 30, -10, 20, -16]
    offset_lt = [-18, 14, -22, 18, 28, -8, 22, -14]
    top_left, top_right, top_top, top_bottom = panel_bounds(top_panel_y)
    lat_left, lat_right, lat_top, lat_bottom = panel_bounds(bottom_panel_y)
    tp_labels_by_idx: dict[int, list[dict[str, Any]]] = {}
    latency_end_labels: list[dict[str, Any]] = []
    for li, label in enumerate(labels):
        color = colors[label]
        rows = rows_by_run[label]

        # Throughput line
        tp_points = []
        for row in rows:
            n = int(row["concurrency"])
            y = float(row["aggregate_tok_s"])
            px, py = chart_xy(panel_y=top_panel_y, x=n, y=y, y_max=tp_max)
            tp_points.append((px, py, row))
        parts.append(
            '<polyline points="{}" fill="none" stroke="{}" stroke-width="3.2"/>'.format(
                " ".join(f"{px:.1f},{py:.1f}" for px, py, _ in tp_points),
                color,
            )
        )
        for pi, (px, py, row) in enumerate(tp_points):
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.4" fill="{color}" stroke="#ffffff" stroke-width="1.2"/>')
            mem = row.get("gpu_mem_peak_total_mb")
            mem_gib = f"{float(mem)/1024.0:.1f}" if isinstance(mem, (int, float)) else "n/a"
            txt = f"{float(row['aggregate_tok_s']):.1f} | {mem_gib}G"
            box_w, box_h = text_box_dims(txt, font_size=10)
            if pi == len(tp_points) - 1:
                box_x = top_right + 10
            elif li % 2 == 0:
                box_x = min(px + 10, top_right - box_w - 6)
            else:
                box_x = max(top_left + 6, px - box_w - 10)
            tp_labels_by_idx.setdefault(pi, []).append(
                {
                    "text": txt,
                    "box_x": box_x,
                    "w": box_w,
                    "h": box_h,
                    "desired_y": py + offset_tp[li % len(offset_tp)],
                    "anchor_x": px,
                    "anchor_y": py,
                    "color": color,
                }
            )

        # Latency lines
        ttft_points = []
        p95_points = []
        for row in rows:
            n = int(row["concurrency"])
            ttft = float(row["avg_ttft_ms"])
            p95 = float(row["p95_latency_s"]) * 1000.0
            ttft_points.append((*chart_xy(panel_y=bottom_panel_y, x=n, y=ttft, y_max=lt_max), row))
            p95_points.append((*chart_xy(panel_y=bottom_panel_y, x=n, y=p95, y_max=lt_max), row))
        parts.append(
            '<polyline points="{}" fill="none" stroke="{}" stroke-width="2.8"/>'.format(
                " ".join(f"{px:.1f},{py:.1f}" for px, py, _ in ttft_points), color
            )
        )
        parts.append(
            '<polyline points="{}" fill="none" stroke="{}" stroke-width="2.8" stroke-dasharray="7 5"/>'.format(
                " ".join(f"{px:.1f},{py:.1f}" for px, py, _ in p95_points), color
            )
        )
        for px, py, _ in ttft_points:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{color}" stroke="#ffffff" stroke-width="1"/>')
        for px, py, _ in p95_points:
            parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="#ffffff" stroke="{color}" stroke-width="1.6"/>')

        # Label final latency point to avoid clutter.
        px_t, py_t, row_last = ttft_points[-1]
        px_p, py_p, _ = p95_points[-1]
        txt = f"{run_display_name(label)}  TTFT {float(row_last['avg_ttft_ms'])/1000.0:.1f}s  P95 {float(row_last['p95_latency_s']):.1f}s"
        box_w, box_h = text_box_dims(txt, font_size=10)
        latency_end_labels.append(
            {
                "text": txt,
                "box_x": lat_right - box_w - 8,
                "w": box_w,
                "h": box_h,
                "desired_y": min(py_t, py_p) + offset_lt[li % len(offset_lt)],
                "anchor_x": px_t,
                "anchor_y": (py_t + py_p) / 2.0,
                "color": color,
            }
        )

    # Throughput point labels: place per-concurrency with collision avoidance.
    for idx in sorted(tp_labels_by_idx):
        group = tp_labels_by_idx[idx]
        max_h = max(float(item["h"]) for item in group)
        ys = distribute_vertical_positions(
            [float(item["desired_y"]) for item in group],
            min_y=top_top + 4,
            max_y=top_bottom - max_h - 4,
            min_gap=max_h + 4,
        )
        for item, box_y in zip(group, ys):
            box_x = clamp(
                float(item["box_x"]),
                margin + 6,
                margin + panel_w - float(item["w"]) - 6,
            )
            parts.append(
                text_box_with_leader(
                    box_x,
                    box_y,
                    str(item["text"]),
                    color=str(item["color"]),
                    anchor_x=float(item["anchor_x"]),
                    anchor_y=float(item["anchor_y"]),
                    font_size=10,
                )
            )

    # Latency end labels: stacked on the right edge to avoid overlap/off-frame text.
    if latency_end_labels:
        max_h = max(float(item["h"]) for item in latency_end_labels)
        ys = distribute_vertical_positions(
            [float(item["desired_y"]) for item in latency_end_labels],
            min_y=lat_top + 4,
            max_y=lat_bottom - max_h - 4,
            min_gap=max_h + 6,
        )
        for item, box_y in zip(latency_end_labels, ys):
            box_x = clamp(
                float(item["box_x"]),
                lat_left + 8,
                margin + panel_w - float(item["w"]) - 6,
            )
            parts.append(
                text_box_with_leader(
                    box_x,
                    box_y,
                    str(item["text"]),
                    color=str(item["color"]),
                    anchor_x=float(item["anchor_x"]),
                    anchor_y=float(item["anchor_y"]),
                    font_size=10,
                )
            )

    parts.append("</svg>")
    return "".join(parts)


def build_summary_rows(
    rows_by_mode: dict[str, tuple[dict[str, list[dict[str, Any]]], list[int]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode_name, (rows_by_run, _conc) in rows_by_mode.items():
        for run_label, rrows in rows_by_run.items():
            if not rrows:
                continue
            best_tp = max(float(r["aggregate_tok_s"]) for r in rrows)
            best_row = max(rrows, key=lambda r: float(r["aggregate_tok_s"]))
            row32 = next((r for r in rrows if int(r["concurrency"]) == 32), rrows[-1])
            mem = row32.get("gpu_mem_peak_total_mb")
            rows.append(
                {
                    "mode": mode_name,
                    "run_label": run_label,
                    "run_name": run_display_name(run_label),
                    "best_tp": best_tp,
                    "best_tp_n": int(best_row["concurrency"]),
                    "tp32": float(row32["aggregate_tok_s"]),
                    "ttft32": float(row32["avg_ttft_ms"]),
                    "p95_32": float(row32["p95_latency_s"]),
                    "mem_gib": (float(mem) / 1024.0) if isinstance(mem, (int, float)) else None,
                    "errors32": int(row32.get("errors", 0)),
                }
            )
    return rows


def draw_summary_table(rows: list[dict[str, Any]], benchmark_title: str) -> str:
    # Highlight best throughput and best (lowest) latencies per mode.
    per_mode: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        per_mode.setdefault(row["mode"], []).append(row)

    best_tp: set[tuple[str, str]] = set()
    best_ttft: set[tuple[str, str]] = set()
    best_p95: set[tuple[str, str]] = set()
    for mode, group in per_mode.items():
        if not group:
            continue
        tp_max = max(g["tp32"] for g in group)
        ttft_min = min(g["ttft32"] for g in group)
        p95_min = min(g["p95_32"] for g in group)
        for g in group:
            key = (mode, g["run_label"])
            if g["tp32"] == tp_max:
                best_tp.add(key)
            if g["ttft32"] == ttft_min:
                best_ttft.add(key)
            if g["p95_32"] == p95_min:
                best_p95.add(key)

    width = 1820
    row_h = 38
    header_h = 46
    top = 96
    cols = [
        ("Load", 170),
        ("Run", 220),
        ("Peak tok/s", 150),
        ("tok/s @32", 120),
        ("TTFT @32 (s)", 130),
        ("P95 @32 (s)", 130),
        ("Peak Mem (GiB)", 140),
        ("Errors @32", 110),
        ("Notes", 620),
    ]
    table_w = sum(w for _, w in cols)
    height = top + header_h + row_h * len(rows) + 170

    x_positions = [24]
    for _, w in cols[:-1]:
        x_positions.append(x_positions[-1] + w)

    parts: list[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    parts.append('<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#f7fbff"/><stop offset="100%" stop-color="#eef5ff"/></linearGradient></defs>')
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="url(#bg)"/>')
    parts.append(
        f'<text x="24" y="42" font-family="ui-monospace, Menlo, Consolas, monospace" '
        f'font-size="30" fill="#0f172a">{esc(benchmark_title)} Summary Table (N=32 focus)</text>'
    )
    parts.append('<text x="24" y="68" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="13" fill="#334155">Highlights: best throughput, lowest TTFT, lowest P95 per load profile</text>')

    # Header
    parts.append(f'<rect x="24" y="{top}" width="{table_w}" height="{header_h}" rx="8" fill="#0f172a"/>')
    for i, (name, _w) in enumerate(cols):
        x = x_positions[i] + 8
        parts.append(
            f'<text x="{x}" y="{top + 30}" font-family="ui-monospace, Menlo, Consolas, monospace" '
            f'font-size="14" fill="#ffffff">{esc(name)}</text>'
        )

    for idx, row in enumerate(rows):
        y = top + header_h + idx * row_h
        mode = row["mode"]
        run_label = row["run_label"]
        key = (mode, run_label)
        base_fill = "#ffffff" if idx % 2 == 0 else "#f9fbff"
        parts.append(f'<rect x="24" y="{y}" width="{table_w}" height="{row_h}" fill="{base_fill}" stroke="#dde6f3" stroke-width="0.8"/>')

        notes = []
        if key in best_tp:
            notes.append("best tok/s")
        if key in best_ttft:
            notes.append("lowest TTFT")
        if key in best_p95:
            notes.append("lowest P95")
        notes_txt = ", ".join(notes) if notes else "-"

        vals = [
            mode,
            row["run_name"],
            f"{row['best_tp']:.1f} @N{row['best_tp_n']}",
            f"{row['tp32']:.1f}",
            f"{row['ttft32']/1000.0:.2f}",
            f"{row['p95_32']:.2f}",
            f"{row['mem_gib']:.1f}" if row["mem_gib"] is not None else "n/a",
            str(row["errors32"]),
            notes_txt,
        ]

        for i, text in enumerate(vals):
            x = x_positions[i] + 8
            txt_color = "#0f172a"
            if i == 8 and notes_txt != "-":
                txt_color = "#0b5d1e"
            parts.append(
                f'<text x="{x}" y="{y + 25}" font-family="ui-monospace, Menlo, Consolas, monospace" '
                f'font-size="13" fill="{txt_color}">{esc(text)}</text>'
            )

        # Cell highlights for key metrics
        if key in best_tp:
            x = x_positions[3]
            parts.append(f'<rect x="{x+1}" y="{y+1}" width="{cols[3][1]-2}" height="{row_h-2}" fill="none" stroke="#0ea5e9" stroke-width="2"/>')
        if key in best_ttft:
            x = x_positions[4]
            parts.append(f'<rect x="{x+1}" y="{y+1}" width="{cols[4][1]-2}" height="{row_h-2}" fill="none" stroke="#16a34a" stroke-width="2"/>')
        if key in best_p95:
            x = x_positions[5]
            parts.append(f'<rect x="{x+1}" y="{y+1}" width="{cols[5][1]-2}" height="{row_h-2}" fill="none" stroke="#a855f7" stroke-width="2"/>')

    # Findings section
    by_mode = {}
    for mode in per_mode:
        group = per_mode[mode]
        best_vllm = max((g for g in group if g["run_label"].startswith("vllm_")), key=lambda g: g["tp32"], default=None)
        best_ollama = max((g for g in group if g["run_label"].startswith("ollama_")), key=lambda g: g["tp32"], default=None)
        if best_vllm and best_ollama and best_ollama["tp32"] > 0:
            by_mode[mode] = best_vllm["tp32"] / best_ollama["tp32"]

    fy = top + header_h + row_h * len(rows) + 48
    parts.append(f'<text x="24" y="{fy}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="17" fill="#0f172a">Key Findings</text>')
    line_y = fy + 24
    for mode in sorted(by_mode):
        parts.append(
            f'<text x="24" y="{line_y}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="14" fill="#111827">'
            f'{esc(mode)}: best vLLM tok/s@32 is {by_mode[mode]:.2f}x best Ollama tok/s@32.</text>'
        )
        line_y += 22
    parts.append(
        f'<text x="24" y="{line_y}" font-family="ui-monospace, Menlo, Consolas, monospace" font-size="14" fill="#111827">'
        'Ollama runs use less peak memory, but vLLM scales much better at higher concurrency.</text>'
    )

    parts.append("</svg>")
    return "".join(parts)


def main() -> int:
    args = parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    varied_path = Path(args.varied)
    fixed_path = Path(args.fixed)

    varied_rows, varied_conc, varied_mode = load_rows(varied_path)
    fixed_rows, fixed_conc, fixed_mode = load_rows(fixed_path)

    varied_svg = draw_combined_chart(
        rows_by_run=varied_rows,
        conc=varied_conc,
        mode_title=varied_mode,
        input_name=varied_path.name,
        benchmark_title=args.benchmark_title,
    )
    fixed_svg = draw_combined_chart(
        rows_by_run=fixed_rows,
        conc=fixed_conc,
        mode_title=fixed_mode,
        input_name=fixed_path.name,
        benchmark_title=args.benchmark_title,
    )

    summary_rows = build_summary_rows(
        {
            "varied_unique_prefix": (varied_rows, varied_conc),
            "fixed_shared_prefix": (fixed_rows, fixed_conc),
        }
    )
    summary_rows.sort(key=lambda r: (r["mode"], ordered_labels([rr["run_label"] for rr in summary_rows]).index(r["run_label"]) if r["run_label"] in ordered_labels([rr["run_label"] for rr in summary_rows]) else 999))
    table_svg = draw_summary_table(summary_rows, benchmark_title=args.benchmark_title)

    varied_out = out_dir / f"{args.output_prefix}_varied_clear_report.svg"
    fixed_out = out_dir / f"{args.output_prefix}_fixed_clear_report.svg"
    table_out = out_dir / f"{args.output_prefix}_metrics_summary_table.svg"
    varied_out.write_text(varied_svg)
    fixed_out.write_text(fixed_svg)
    table_out.write_text(table_svg)

    print(varied_out)
    print(fixed_out)
    print(table_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
