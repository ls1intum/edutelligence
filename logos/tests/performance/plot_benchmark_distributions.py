#!/usr/bin/env python3
"""
Generate bell-curve distribution plots for benchmark results.

Reads the detailed CSV from run_api_workload.py and produces:
  1. TTFT distribution (bell curve with percentile markers)
  2. Total latency distribution (bell curve with percentile markers)
  3. Combined summary stats table (printed + saved)
  4. Per-model breakdown
  5. Operations summary (cold starts, sleeps, wakes)

Usage:
    python3 tests/performance/plot_benchmark_distributions.py \
        --csv tests/performance/results/.../detailed.csv
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


# ── Colors ──────────────────────────────────────────────────────────────

COLOR_FILL = "#C8A415"       # gold fill (like the screenshot)
COLOR_EDGE = "#2255A0"       # blue outline
COLOR_P50 = "#1a7a1a"        # green — median
COLOR_MEAN = "#cc6600"       # orange — mean
COLOR_P95 = "#cc2222"        # red — p95
COLOR_P99 = "#8822aa"        # purple — p99
COLOR_GRID = "#cccccc"
BG_COLOR = "#f5f5f5"


# ── Helpers ─────────────────────────────────────────────────────────────

def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(data):
        return data[-1]
    return data[f] + (k - f) * (data[c] - data[f])


def stats_block(data: list[float]) -> dict[str, float]:
    s = sorted(data)
    return {
        "count": len(s),
        "min": s[0] if s else 0,
        "max": s[-1] if s else 0,
        "mean": sum(s) / len(s) if s else 0,
        "median": percentile(s, 50),
        "p90": percentile(s, 90),
        "p95": percentile(s, 95),
        "p99": percentile(s, 99),
        "stdev": (sum((x - sum(s)/len(s))**2 for x in s) / len(s)) ** 0.5 if s else 0,
    }


def gaussian_kde(data: list[float], x_grid: np.ndarray, bandwidth: Optional[float] = None) -> np.ndarray:
    """Simple Gaussian KDE (no scipy dependency)."""
    n = len(data)
    if n == 0:
        return np.zeros_like(x_grid)
    if bandwidth is None:
        std = float(np.std(data))
        bandwidth = 1.06 * std * n ** (-1.0 / 5.0)
        if bandwidth <= 0:
            bandwidth = 1.0
    result = np.zeros_like(x_grid, dtype=float)
    for xi in data:
        result += np.exp(-0.5 * ((x_grid - xi) / bandwidth) ** 2)
    result /= (n * bandwidth * math.sqrt(2 * math.pi))
    return result


# ── Plotting ────────────────────────────────────────────────────────────

def plot_distribution(
    data: list[float],
    title: str,
    xlabel: str,
    output_path: Path,
    *,
    unit: str = "ms",
    model_label: str = "",
) -> None:
    """Plot a bell-curve distribution with percentile markers."""
    if len(data) < 3:
        print(f"  Skipping {title}: only {len(data)} data points")
        return

    st = stats_block(data)
    s = sorted(data)

    fig, ax = plt.subplots(figsize=(12, 6.5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor("white")

    # Histogram + KDE
    n_bins = min(max(int(len(data) ** 0.5) * 2, 20), 80)
    counts, bin_edges, patches = ax.hist(
        data, bins=n_bins, density=True,
        color=COLOR_FILL, edgecolor=COLOR_EDGE, alpha=0.8,
        linewidth=0.5, zorder=2,
    )

    # KDE curve
    x_min = max(s[0] - st["stdev"], 0)
    x_max = s[-1] + st["stdev"]
    x_grid = np.linspace(x_min, x_max, 500)
    kde = gaussian_kde(data, x_grid)
    ax.plot(x_grid, kde, color=COLOR_EDGE, linewidth=2.5, zorder=3, label="_kde")

    # Fill under KDE
    ax.fill_between(x_grid, kde, alpha=0.15, color=COLOR_EDGE, zorder=2)

    y_max = max(counts.max(), kde.max()) * 1.25

    # Percentile lines
    markers = [
        ("Median (P50)", st["median"], COLOR_P50, "--", 2.0),
        ("Mean", st["mean"], COLOR_MEAN, "-.", 1.8),
        ("P95", st["p95"], COLOR_P95, "--", 2.0),
        ("P99", st["p99"], COLOR_P99, ":", 2.0),
    ]
    for label, val, color, ls, lw in markers:
        ax.axvline(val, color=color, linestyle=ls, linewidth=lw, zorder=4)
        ax.annotate(
            f"{label}\n{val:,.0f}{unit}",
            xy=(val, y_max * 0.92),
            fontsize=8, fontweight="bold", color=color,
            ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=color, alpha=0.9),
            zorder=5,
        )

    # Stats text box
    stats_text = (
        f"n={st['count']}   "
        f"min={st['min']:,.0f}   "
        f"max={st['max']:,.0f}   "
        f"stdev={st['stdev']:,.0f}{unit}\n"
        f"mean={st['mean']:,.0f}   "
        f"median={st['median']:,.0f}   "
        f"P90={st['p90']:,.0f}   "
        f"P95={st['p95']:,.0f}   "
        f"P99={st['p99']:,.0f}{unit}"
    )
    ax.text(
        0.98, 0.02, stats_text,
        transform=ax.transAxes, fontsize=8, fontfamily="monospace",
        va="bottom", ha="right",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="#999999", alpha=0.9),
        zorder=5,
    )

    # Formatting
    subtitle = f"  [{model_label}]" if model_label else ""
    ax.set_title(f"{title}{subtitle}", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel("Density", fontsize=11)
    ax.set_ylim(0, y_max)
    ax.grid(True, alpha=0.3, color=COLOR_GRID, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color=COLOR_P50, linestyle="--", lw=2, label=f"Median: {st['median']:,.0f}{unit}"),
        Line2D([0], [0], color=COLOR_MEAN, linestyle="-.", lw=2, label=f"Mean: {st['mean']:,.0f}{unit}"),
        Line2D([0], [0], color=COLOR_P95, linestyle="--", lw=2, label=f"P95: {st['p95']:,.0f}{unit}"),
        Line2D([0], [0], color=COLOR_P99, linestyle=":", lw=2, label=f"P99: {st['p99']:,.0f}{unit}"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=9, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


def plot_combined_distribution(
    models_data: dict[str, dict[str, list]],
    metric_key: str,
    title: str,
    xlabel: str,
    output_path: Path,
    *,
    unit: str = "ms",
) -> None:
    """Single bell-curve chart with all models overlaid + overall percentile markers."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    # Gather all values and per-model values
    all_values = []
    model_values: dict[str, list[float]] = {}
    for model, md in sorted(models_data.items()):
        vals = md.get(metric_key, [])
        if vals:
            short = model.split("/")[-1] if "/" in model else model
            model_values[short] = vals
            all_values.extend(vals)

    if len(all_values) < 3:
        print(f"  Skipping {title}: only {len(all_values)} data points")
        return

    st = stats_block(all_values)
    s = sorted(all_values)

    # Model colors
    model_palette = ["#2255A0", "#C8A415", "#CC4444", "#22AA66", "#8844CC"]
    model_color_map = {}
    for i, name in enumerate(sorted(model_values.keys())):
        model_color_map[name] = model_palette[i % len(model_palette)]

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor("white")

    # KDE grid spanning all data
    x_min = max(s[0] - st["stdev"] * 0.5, 0)
    x_max = s[-1] + st["stdev"] * 0.5
    x_grid = np.linspace(x_min, x_max, 600)

    # Per-model: histogram (semi-transparent) + KDE curve
    for model_name, vals in sorted(model_values.items()):
        color = model_color_map[model_name]
        n_bins = min(max(int(len(vals) ** 0.5) * 2, 15), 60)
        ax.hist(
            vals, bins=n_bins, density=True,
            color=color, alpha=0.25, edgecolor=color,
            linewidth=0.3, zorder=2,
        )
        kde = gaussian_kde(vals, x_grid)
        ax.plot(x_grid, kde, color=color, linewidth=2.5, zorder=3)
        ax.fill_between(x_grid, kde, alpha=0.08, color=color, zorder=2)

    # Overall KDE (black dashed)
    kde_all = gaussian_kde(all_values, x_grid)
    ax.plot(x_grid, kde_all, color="#333333", linewidth=2.0, linestyle="--", zorder=3, alpha=0.6)

    y_max = kde_all.max()
    for vals in model_values.values():
        km = gaussian_kde(vals, x_grid).max()
        if km > y_max:
            y_max = km
    y_max *= 1.35

    # Percentile lines (overall)
    markers = [
        ("Median (P50)", st["median"], COLOR_P50, "--", 2.2),
        ("Mean", st["mean"], COLOR_MEAN, "-.", 2.0),
        ("P95", st["p95"], COLOR_P95, "--", 2.2),
        ("P99", st["p99"], COLOR_P99, ":", 2.2),
    ]
    # Stagger annotation heights to avoid overlap
    heights = [0.95, 0.85, 0.95, 0.85]
    val_fmt = ",.1f" if unit == "s" else ",.0f"
    for (label, val, color, ls, lw), h in zip(markers, heights):
        ax.axvline(val, color=color, linestyle=ls, linewidth=lw, zorder=4, alpha=0.85)
        ax.annotate(
            f"{label}\n{val:{val_fmt}}{unit}",
            xy=(val, y_max * h),
            fontsize=9, fontweight="bold", color=color,
            ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=color, alpha=0.92),
            zorder=5,
        )

    # Per-model stats in bottom-right
    lines = []
    for model_name, vals in sorted(model_values.items()):
        mst = stats_block(vals)
        lines.append(
            f"{model_name} (n={mst['count']})  "
            f"median={mst['median']:{val_fmt}}  p95={mst['p95']:{val_fmt}}  p99={mst['p99']:{val_fmt}}{unit}"
        )
    lines.append(
        f"Overall (n={st['count']})  "
        f"median={st['median']:{val_fmt}}  p95={st['p95']:{val_fmt}}  p99={st['p99']:{val_fmt}}  "
        f"stdev={st['stdev']:{val_fmt}}{unit}"
    )
    ax.text(
        0.98, 0.02, "\n".join(lines),
        transform=ax.transAxes, fontsize=8, fontfamily="monospace",
        va="bottom", ha="right",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="#999999", alpha=0.92),
        zorder=5,
    )

    ax.set_title(title, fontsize=15, fontweight="bold", pad=14)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel("Density", fontsize=12)
    ax.set_ylim(0, y_max)
    ax.grid(True, alpha=0.3, color=COLOR_GRID, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Legend: models + percentile lines
    legend_elements = []
    for model_name in sorted(model_values.keys()):
        legend_elements.append(
            Patch(facecolor=model_color_map[model_name], alpha=0.5, label=model_name)
        )
    legend_elements.append(
        Line2D([0], [0], color="#333333", linestyle="--", lw=2, alpha=0.6, label="Overall")
    )
    legend_elements.append(Line2D([0], [0], color=COLOR_P50, linestyle="--", lw=2, label=f"Median: {st['median']:{val_fmt}}{unit}"))
    legend_elements.append(Line2D([0], [0], color=COLOR_MEAN, linestyle="-.", lw=2, label=f"Mean: {st['mean']:{val_fmt}}{unit}"))
    legend_elements.append(Line2D([0], [0], color=COLOR_P95, linestyle="--", lw=2, label=f"P95: {st['p95']:{val_fmt}}{unit}"))
    legend_elements.append(Line2D([0], [0], color=COLOR_P99, linestyle=":", lw=2, label=f"P99: {st['p99']:{val_fmt}}{unit}"))
    ax.legend(handles=legend_elements, loc="upper right", fontsize=9, framealpha=0.92)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


def plot_timeline(
    records: list[dict],
    output_path: Path,
) -> None:
    """Plot request latencies over time, colored by model."""
    if not records:
        return

    models = sorted(set(r["model_name"] for r in records if r.get("model_name")))
    model_colors = {}
    palette = ["#2255A0", "#C8A415", "#CC4444", "#22AA66", "#8844CC"]
    for i, m in enumerate(models):
        model_colors[m] = palette[i % len(palette)]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    fig.patch.set_facecolor(BG_COLOR)
    for ax in (ax1, ax2):
        ax.set_facecolor("white")

    for rec in records:
        model = rec.get("model_name", "unknown")
        color = model_colors.get(model, "#888888")
        t = rec.get("_offset_s", 0)

        ttft = rec.get("ttft_ms")
        if isinstance(ttft, (int, float)) and ttft > 0:
            ax1.scatter(t, ttft / 1000.0, c=color, s=12, alpha=0.6, zorder=2)

        latency = rec.get("total_latency_ms")
        if isinstance(latency, (int, float)) and latency > 0:
            ax2.scatter(t, latency / 1000.0, c=color, s=12, alpha=0.6, zorder=2)

    ax1.set_ylabel("TTFT (seconds)", fontsize=11)
    ax1.set_title("TTFT Over Time", fontsize=13, fontweight="bold")
    ax1.grid(True, alpha=0.3)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False)

    ax2.set_ylabel("Total Latency (seconds)", fontsize=11)
    ax2.set_xlabel("Time (seconds into benchmark)", fontsize=11)
    ax2.set_title("Total Latency Over Time", fontsize=13, fontweight="bold")
    ax2.grid(True, alpha=0.3)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=model_colors[m], label=m.split("/")[-1])
        for m in models
    ]
    ax1.legend(handles=legend_elements, loc="upper right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


# ── Main ────────────────────────────────────────────────────────────────

def load_records(csv_path: Path) -> list[dict]:
    records = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = {}
            for k, v in row.items():
                if v == "" or v is None:
                    rec[k] = None
                else:
                    try:
                        rec[k] = float(v)
                    except ValueError:
                        rec[k] = v
            records.append(rec)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot benchmark distribution charts")
    parser.add_argument("--csv", type=Path, required=True, help="Path to detailed results CSV")
    parser.add_argument("--out-dir", type=Path, help="Output directory (default: same as CSV)")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: {args.csv} not found")
        sys.exit(1)

    out_dir = args.out_dir or args.csv.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.csv.stem.replace("_detailed", "")

    records = load_records(args.csv)
    print(f"Loaded {len(records)} records from {args.csv}")

    # Filter successful
    ok_records = [
        r for r in records
        if r.get("http_status") is not None
        and int(r["http_status"]) == 200
        and r.get("total_latency_ms") is not None
    ]
    print(f"  Successful: {len(ok_records)} / {len(records)}")
    failed = [r for r in records if r.get("http_status") is not None and int(r["http_status"]) != 200]
    if failed:
        status_counts = {}
        for r in failed:
            s = int(r["http_status"])
            status_counts[s] = status_counts.get(s, 0) + 1
        print(f"  Failed: {len(failed)} — {status_counts}")

    # Compute time offset for timeline
    arrival_offsets = []
    for r in ok_records:
        rid = r.get("request_id", "")
        # Try to extract from workload; fallback to sequential index
        arrival_offsets.append(r)
    # Use queue_wait_ms + processing_ms to infer relative time, or just use index
    for i, r in enumerate(ok_records):
        r["_offset_s"] = i  # will be overridden below if we have arrival data

    # Try to compute offset from request timing
    # Use client_duration and completion order to estimate
    ttft_values = []
    latency_values = []
    queue_values = []
    processing_values = []
    cold_starts = 0
    total_load_duration_ms = 0.0

    models_data: dict[str, dict[str, list]] = {}

    for i, r in enumerate(ok_records):
        model = str(r.get("model_name") or "unknown")
        if model not in models_data:
            models_data[model] = {"ttft": [], "latency": [], "queue": [], "processing": []}

        ttft = r.get("ttft_ms")
        if isinstance(ttft, (int, float)) and ttft > 0:
            ttft_values.append(ttft)
            models_data[model]["ttft"].append(ttft)

        lat = r.get("total_latency_ms")
        if isinstance(lat, (int, float)) and lat > 0:
            latency_values.append(lat)
            models_data[model]["latency"].append(lat)

        qw = r.get("queue_wait_ms")
        if isinstance(qw, (int, float)) and qw >= 0:
            queue_values.append(qw)
            models_data[model]["queue"].append(qw)

        pm = r.get("processing_ms")
        if isinstance(pm, (int, float)) and pm >= 0:
            processing_values.append(pm)
            models_data[model]["processing"].append(pm)

        cs = r.get("cold_start")
        if cs and str(cs).lower() in ("true", "1", "1.0"):
            cold_starts += 1

        ld = r.get("load_duration_ms")
        if isinstance(ld, (int, float)) and ld > 0:
            total_load_duration_ms += ld

        r["_offset_s"] = i * 0.5  # rough timeline spacing

    # ── Print stats ─────────────────────────────────────────────────
    print()
    print("=" * 72)
    print("  BENCHMARK RESULTS SUMMARY")
    print("=" * 72)

    def print_stats(label: str, values: list[float], unit: str = "ms") -> None:
        if not values:
            print(f"\n  {label}: no data")
            return
        st = stats_block(values)
        print(f"\n  {label} (n={st['count']})")
        print(f"    Min:    {st['min']:>10,.1f} {unit}")
        print(f"    Mean:   {st['mean']:>10,.1f} {unit}")
        print(f"    Median: {st['median']:>10,.1f} {unit}")
        print(f"    P90:    {st['p90']:>10,.1f} {unit}")
        print(f"    P95:    {st['p95']:>10,.1f} {unit}")
        print(f"    P99:    {st['p99']:>10,.1f} {unit}")
        print(f"    Max:    {st['max']:>10,.1f} {unit}")
        print(f"    Stdev:  {st['stdev']:>10,.1f} {unit}")

    print_stats("TTFT (Time to First Token)", ttft_values)
    print_stats("Total Latency", latency_values)
    print_stats("Queue Wait", queue_values)
    print_stats("Processing Time", processing_values)

    print(f"\n  Operations:")
    print(f"    Cold starts:       {cold_starts}")
    print(f"    Total load time:   {total_load_duration_ms:,.0f} ms")
    print(f"    Success rate:      {len(ok_records)}/{len(records)} ({100*len(ok_records)/max(len(records),1):.1f}%)")

    # Per-model breakdown
    for model, md in sorted(models_data.items()):
        short = model.split("/")[-1] if "/" in model else model
        print(f"\n  ── {short} ──")
        if md["ttft"]:
            st = stats_block(md["ttft"])
            print(f"    TTFT:    median={st['median']:,.0f}ms  p95={st['p95']:,.0f}ms  p99={st['p99']:,.0f}ms  (n={st['count']})")
        if md["latency"]:
            st = stats_block(md["latency"])
            print(f"    Latency: median={st['median']:,.0f}ms  p95={st['p95']:,.0f}ms  p99={st['p99']:,.0f}ms  (n={st['count']})")

    print("\n" + "=" * 72)

    # ── Generate plots ──────────────────────────────────────────────
    print("\nGenerating distribution plots...")

    # Combined multi-model distribution charts (in seconds)
    if models_data and ttft_values:
        plot_combined_distribution(
            {m: {k: [v / 1000.0 for v in vs] if k == "ttft" else vs for k, vs in md.items()}
             for m, md in models_data.items()},
            "ttft",
            "Time to First Token (TTFT) — All Models",
            "TTFT (seconds)",
            out_dir / f"{stem}_ttft_combined.png",
            unit="s",
        )

    if models_data and latency_values:
        plot_combined_distribution(
            {m: {k: [v / 1000.0 for v in vs] if k == "latency" else vs for k, vs in md.items()}
             for m, md in models_data.items()},
            "latency",
            "Total Latency — All Models",
            "Total Latency (seconds)",
            out_dir / f"{stem}_latency_combined.png",
            unit="s",
        )

    if models_data and queue_values:
        plot_combined_distribution(
            {m: {k: [v / 1000.0 for v in vs] if k == "queue" else vs for k, vs in md.items()}
             for m, md in models_data.items()},
            "queue",
            "Queue Wait Time — All Models",
            "Queue Wait (seconds)",
            out_dir / f"{stem}_queue_combined.png",
            unit="s",
        )

    # Timeline
    plot_timeline(ok_records, out_dir / f"{stem}_timeline.png")

    print(f"\nAll plots saved to: {out_dir}")


if __name__ == "__main__":
    main()
