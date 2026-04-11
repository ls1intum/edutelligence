#!/usr/bin/env python3
"""
Plot Ollama vs vLLM total latency distributions side-by-side.

For each workload size (150, 300, 600), overlays the overall total_latency_ms
distributions from both engines on a single chart with matching density scale.

Usage:
    python3 tests/performance/plot_ollama_vs_vllm.py
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

RUNS = [
    {
        "label": "150 requests",
        "tag": "150req",
        "vllm_csv": BASE / "results/hw3_random_10m_150req_resolver60s/results_detailed.csv",
        "ollama_csv": sorted((BASE / "results_ollama/hw3_random_10m_150req").glob("*/results_detailed.csv"))[-1],
    },
    {
        "label": "300 requests",
        "tag": "300req",
        "vllm_csv": BASE / "results/hw3_random_10m_300req_resolver60s/results_detailed.csv",
        "ollama_csv": sorted((BASE / "results_ollama/hw3_random_10m_300req").glob("*/results_detailed.csv"))[-1],
    },
    {
        "label": "600 requests",
        "tag": "600req",
        "vllm_csv": sorted((BASE / "results/oversubscribed_3x").glob("*600req_resolver60s_3x/detailed.csv"))[-1],
        "ollama_csv": sorted((BASE / "results_ollama/hw3_random_10m_600req").glob("*/results_detailed.csv"))[-1],
    },
]

OUT_DIR = BASE / "results_ollama_vs_vllm"

# ── Colors ─────────────────────────────────────────────────────────────

VLLM_COLOR = "#2255A0"      # blue
OLLAMA_COLOR = "#CC4444"     # red
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


def load_latencies(csv_path: Path) -> list[float]:
    """Load total_latency_ms for successful (HTTP 200) requests."""
    values = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                status = int(row.get("http_status", 0))
                lat = float(row.get("total_latency_ms", 0))
            except (ValueError, TypeError):
                continue
            if status == 200 and lat > 0:
                values.append(lat)
    return sorted(values)


# ── Plotting ───────────────────────────────────────────────────────────

def plot_comparison(
    vllm_data: list[float],
    ollama_data: list[float],
    title: str,
    out_path: Path,
) -> None:
    from matplotlib.lines import Line2D

    # Convert ms → seconds
    vllm_data = [v / 1000.0 for v in vllm_data]
    ollama_data = [v / 1000.0 for v in ollama_data]

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor("white")

    # Compute shared x range
    all_data = vllm_data + ollama_data
    all_sorted = sorted(all_data)
    overall_std = stats_block(all_data)["stdev"]
    x_min = max(all_sorted[0] - overall_std * 0.3, 0)
    x_max = all_sorted[-1] + overall_std * 0.3
    x_grid = np.linspace(x_min, x_max, 800)

    y_max = 0.0

    # Shared bin edges so both engines have identical bar widths
    n_bins = min(max(int(len(all_data) ** 0.5) * 3, 40), 120)
    bin_edges = np.linspace(x_min, x_max, n_bins + 1)
    bin_width = bin_edges[1] - bin_edges[0]
    kde_bw = bin_width * 0.9  # tie KDE smoothing to bin size

    # --- vLLM ---
    vllm_st = stats_block(vllm_data)
    counts_v, _, _ = ax.hist(
        vllm_data, bins=bin_edges, density=True,
        color=VLLM_COLOR, alpha=0.30, edgecolor=VLLM_COLOR,
        linewidth=0.4, zorder=2,
    )
    kde_v = gaussian_kde(vllm_data, x_grid, bandwidth=kde_bw)
    ax.plot(x_grid, kde_v, color=VLLM_COLOR, linewidth=3.0, zorder=4)
    ax.fill_between(x_grid, kde_v, alpha=0.10, color=VLLM_COLOR, zorder=2)
    y_max = max(y_max, counts_v.max(), kde_v.max())

    # --- Ollama ---
    ollama_st = stats_block(ollama_data)
    counts_o, _, _ = ax.hist(
        ollama_data, bins=bin_edges, density=True,
        color=OLLAMA_COLOR, alpha=0.30, edgecolor=OLLAMA_COLOR,
        linewidth=0.4, zorder=2,
    )
    kde_o = gaussian_kde(ollama_data, x_grid, bandwidth=kde_bw)
    ax.plot(x_grid, kde_o, color=OLLAMA_COLOR, linewidth=3.0, zorder=4)
    ax.fill_between(x_grid, kde_o, alpha=0.10, color=OLLAMA_COLOR, zorder=2)
    y_max = max(y_max, counts_o.max(), kde_o.max())

    y_max *= 1.35

    # Percentile lines — vLLM (solid)
    for val, ls, lw in [(vllm_st["median"], "--", 2.2), (vllm_st["p95"], "--", 2.0)]:
        ax.axvline(val, color=VLLM_COLOR, linestyle=ls, linewidth=lw, zorder=5, alpha=0.8)

    # Percentile lines — Ollama (solid)
    for val, ls, lw in [(ollama_st["median"], "--", 2.2), (ollama_st["p95"], "--", 2.0)]:
        ax.axvline(val, color=OLLAMA_COLOR, linestyle=ls, linewidth=lw, zorder=5, alpha=0.8)

    # Annotations — LogosWorkerNode
    ax.annotate(
        f"Logos P50\n{vllm_st['median']:,.1f}s",
        xy=(vllm_st["median"], y_max * 0.92),
        fontsize=8, fontweight="bold", color=VLLM_COLOR,
        ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=VLLM_COLOR, alpha=0.9),
        zorder=6,
    )
    ax.annotate(
        f"Logos P95\n{vllm_st['p95']:,.1f}s",
        xy=(vllm_st["p95"], y_max * 0.78),
        fontsize=8, fontweight="bold", color=VLLM_COLOR,
        ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=VLLM_COLOR, alpha=0.9),
        zorder=6,
    )

    # Annotations — Ollama
    ax.annotate(
        f"Ollama P50\n{ollama_st['median']:,.1f}s",
        xy=(ollama_st["median"], y_max * 0.92),
        fontsize=8, fontweight="bold", color=OLLAMA_COLOR,
        ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=OLLAMA_COLOR, alpha=0.9),
        zorder=6,
    )
    ax.annotate(
        f"Ollama P95\n{ollama_st['p95']:,.1f}s",
        xy=(ollama_st["p95"], y_max * 0.78),
        fontsize=8, fontweight="bold", color=OLLAMA_COLOR,
        ha="center", va="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=OLLAMA_COLOR, alpha=0.9),
        zorder=6,
    )

    # Formatting
    ax.set_title(title, fontsize=15, fontweight="bold", pad=14)
    ax.set_xlabel("Total Latency (s)", fontsize=12)
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
        Line2D([0], [0], color=VLLM_COLOR, linewidth=3, label="LogosWorkerNode"),
        Line2D([0], [0], color=OLLAMA_COLOR, linewidth=3, label="Ollama"),
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

    for run in RUNS:
        print(f"\n{'─' * 60}")
        print(f"  {run['label']}")
        print(f"{'─' * 60}")

        vllm_csv = run["vllm_csv"]
        ollama_csv = run["ollama_csv"]

        if not vllm_csv.exists():
            print(f"  ERROR: vLLM CSV not found: {vllm_csv}")
            continue
        if not ollama_csv.exists():
            print(f"  ERROR: Ollama CSV not found: {ollama_csv}")
            continue

        vllm_data = load_latencies(vllm_csv)
        ollama_data = load_latencies(ollama_csv)

        print(f"  vLLM:   {len(vllm_data)} successful requests")
        print(f"  Ollama: {len(ollama_data)} successful requests")

        out_path = OUT_DIR / f"comparison_total_latency_{run['tag']}.png"
        plot_comparison(
            vllm_data, ollama_data,
            title=f"Total Latency Distribution — LogosWorkerNode vs Ollama\n{run['label']} over 10 min",
            out_path=out_path,
        )

    print(f"\nAll comparison charts saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
