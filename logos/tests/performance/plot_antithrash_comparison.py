#!/usr/bin/env python3
"""
Plot anti-thrash fix comparison: before vs after.

Compares the TTFT and total latency distributions between the broken
anti-thrash run and the v2 fix run.

Usage:
    python3 tests/performance/plot_antithrash_comparison.py
"""
from __future__ import annotations

import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────

BASE = Path(__file__).resolve().parent

_before_matches = sorted((BASE / "results/legacy/explicit/10m").glob("20260411_073057*/*detailed.csv"))
BEFORE_CSV = _before_matches[-1] if _before_matches else None
_after_matches = sorted((BASE / "results/legacy/explicit/10m").glob("20260411_125849*/*detailed.csv"))
AFTER_CSV = _after_matches[-1] if _after_matches else None

OUT_DIR = BASE / "results/legacy/results_ollama_vs_vllm"

# ── Colors ─────────────────────────────────────────────────────────────

BEFORE_COLOR = "#CC4444"     # red
AFTER_COLOR = "#2255A0"      # blue
BG_COLOR = "#f5f5f5"
COLOR_GRID = "#cccccc"


# ── Helpers ────────────────────────────────────────────────────────────

def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    k = (len(data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(data):
        return data[-1]
    return data[f] + (data[c] - data[f]) * (k - f)


def stats_block(data: list[float]) -> dict[str, float]:
    s = sorted(data)
    n = len(s)
    mean = sum(s) / n
    variance = sum((x - mean) ** 2 for x in s) / n
    return {
        "count": n,
        "min": s[0],
        "max": s[-1],
        "mean": mean,
        "median": percentile(s, 50),
        "p90": percentile(s, 90),
        "p95": percentile(s, 95),
        "p99": percentile(s, 99),
        "stdev": math.sqrt(variance),
    }


def gaussian_kde(data: list[float], x_grid: np.ndarray, bandwidth: float | None = None) -> np.ndarray:
    n = len(data)
    if bandwidth is None:
        s = sorted(data)
        mean = sum(s) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in s) / n) or 1.0
        iqr = percentile(s, 75) - percentile(s, 25)
        h = 0.9 * min(std, iqr / 1.34) * n ** (-0.2) if iqr > 0 else 1.06 * std * n ** (-0.2)
        bandwidth = max(h, 1e-6)
    arr = np.asarray(data)
    result = np.zeros_like(x_grid, dtype=float)
    for xi in arr:
        result += np.exp(-0.5 * ((x_grid - xi) / bandwidth) ** 2)
    result /= (n * bandwidth * math.sqrt(2 * math.pi))
    return result


def load_metric(csv_path: Path, metric: str) -> list[float]:
    """Load a metric column for successful (HTTP 200) requests."""
    values = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                status = int(row.get("http_status", 0))
                val = float(row.get(metric, 0))
            except (ValueError, TypeError):
                continue
            if status == 200 and val > 0:
                values.append(val)
    return sorted(values)


# ── Plotting ───────────────────────────────────────────────────────────

def plot_comparison(
    before_data: list[float],
    after_data: list[float],
    title: str,
    xlabel: str,
    out_path: Path,
    before_label: str = "Before (anti-thrash v1)",
    after_label: str = "After (anti-thrash v2)",
) -> None:
    from matplotlib.lines import Line2D

    # Convert ms -> seconds
    before_data = [v / 1000.0 for v in before_data]
    after_data = [v / 1000.0 for v in after_data]

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor("white")

    # Compute shared x range
    all_data = before_data + after_data
    all_sorted = sorted(all_data)
    overall_std = stats_block(all_data)["stdev"]
    x_min = max(all_sorted[0] - overall_std * 0.3, 0)
    x_max = all_sorted[-1] + overall_std * 0.3
    x_grid = np.linspace(x_min, x_max, 800)

    y_max = 0.0

    # Shared bin edges
    n_bins = min(max(int(len(all_data) ** 0.5) * 3, 40), 120)
    bin_edges = np.linspace(x_min, x_max, n_bins + 1)
    bin_width = bin_edges[1] - bin_edges[0]
    kde_bw = bin_width * 0.9

    # --- Before ---
    before_st = stats_block(before_data)
    counts_b, _, _ = ax.hist(
        before_data, bins=bin_edges, density=True,
        color=BEFORE_COLOR, alpha=0.30, edgecolor=BEFORE_COLOR,
        linewidth=0.4, zorder=2,
    )
    kde_b = gaussian_kde(before_data, x_grid, bandwidth=kde_bw)
    ax.plot(x_grid, kde_b, color=BEFORE_COLOR, linewidth=3.0, zorder=4)
    ax.fill_between(x_grid, kde_b, alpha=0.10, color=BEFORE_COLOR, zorder=2)
    y_max = max(y_max, counts_b.max(), kde_b.max())

    # --- After ---
    after_st = stats_block(after_data)
    counts_a, _, _ = ax.hist(
        after_data, bins=bin_edges, density=True,
        color=AFTER_COLOR, alpha=0.30, edgecolor=AFTER_COLOR,
        linewidth=0.4, zorder=2,
    )
    kde_a = gaussian_kde(after_data, x_grid, bandwidth=kde_bw)
    ax.plot(x_grid, kde_a, color=AFTER_COLOR, linewidth=3.0, zorder=4)
    ax.fill_between(x_grid, kde_a, alpha=0.10, color=AFTER_COLOR, zorder=2)
    y_max = max(y_max, counts_a.max(), kde_a.max())

    y_max *= 1.35

    # Percentile lines
    for val, ls, lw in [(before_st["median"], "--", 2.2), (before_st["p95"], "--", 2.0), (before_st["p99"], ":", 2.0)]:
        ax.axvline(val, color=BEFORE_COLOR, linestyle=ls, linewidth=lw, zorder=5, alpha=0.8)
    for val, ls, lw in [(after_st["median"], "--", 2.2), (after_st["p95"], "--", 2.0), (after_st["p99"], ":", 2.0)]:
        ax.axvline(val, color=AFTER_COLOR, linestyle=ls, linewidth=lw, zorder=5, alpha=0.8)

    # Annotations — Before
    for label, val, h in [("P50", before_st["median"], 0.92), ("P95", before_st["p95"], 0.78), ("P99", before_st["p99"], 0.64)]:
        ax.annotate(
            f"{label}\n{val:,.1f}s",
            xy=(val, y_max * h),
            fontsize=8, fontweight="bold", color=BEFORE_COLOR,
            ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=BEFORE_COLOR, alpha=0.9),
            zorder=6,
        )

    # Annotations — After
    for label, val, h in [("P50", after_st["median"], 0.92), ("P95", after_st["p95"], 0.78), ("P99", after_st["p99"], 0.64)]:
        ax.annotate(
            f"{label}\n{val:,.1f}s",
            xy=(val, y_max * h),
            fontsize=8, fontweight="bold", color=AFTER_COLOR,
            ha="center", va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=AFTER_COLOR, alpha=0.9),
            zorder=6,
        )

    # Formatting
    ax.set_title(title, fontsize=15, fontweight="bold", pad=14)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel("Density", fontsize=12)
    ax.set_xlim(left=0)
    ax.set_ylim(0, y_max)
    ax.yaxis.set_tick_params(labelleft=False)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.grid(True, alpha=0.3, color=COLOR_GRID, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Legend
    legend_elements = [
        Line2D([0], [0], color=BEFORE_COLOR, linewidth=3, label=before_label),
        Line2D([0], [0], color=AFTER_COLOR, linewidth=3, label=after_label),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=11, framealpha=0.95,
              edgecolor="#999999", fancybox=True)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {out_path}")


# ── Main ───────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Before CSV: {BEFORE_CSV}")
    print(f"After CSV:  {AFTER_CSV}")

    # TTFT comparison
    before_ttft = load_metric(BEFORE_CSV, "ttft_ms")
    after_ttft = load_metric(AFTER_CSV, "ttft_ms")
    print(f"\nTTFT: before={len(before_ttft)}, after={len(after_ttft)} successful requests")

    plot_comparison(
        before_ttft, after_ttft,
        title="TTFT Distribution — Anti-thrash v1 vs v2 Fix\n600 requests over 10 min",
        xlabel="Time To First Token (s)",
        out_path=OUT_DIR / "comparison_ttft_antithrash_v1_vs_v2.png",
    )

    # Total latency comparison
    before_lat = load_metric(BEFORE_CSV, "total_latency_ms")
    after_lat = load_metric(AFTER_CSV, "total_latency_ms")
    print(f"Total latency: before={len(before_lat)}, after={len(after_lat)} successful requests")

    plot_comparison(
        before_lat, after_lat,
        title="Total Latency Distribution — Anti-thrash v1 vs v2 Fix\n600 requests over 10 min",
        xlabel="Total Latency (s)",
        out_path=OUT_DIR / "comparison_total_latency_antithrash_v1_vs_v2.png",
    )

    # Queue wait comparison
    before_qw = load_metric(BEFORE_CSV, "queue_wait_ms")
    after_qw = load_metric(AFTER_CSV, "queue_wait_ms")
    print(f"Queue wait: before={len(before_qw)}, after={len(after_qw)} successful requests")

    plot_comparison(
        before_qw, after_qw,
        title="Queue Wait Distribution — Anti-thrash v1 vs v2 Fix\n600 requests over 10 min",
        xlabel="Queue Wait Time (s)",
        out_path=OUT_DIR / "comparison_queue_wait_antithrash_v1_vs_v2.png",
    )

    print(f"\nAll charts saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
