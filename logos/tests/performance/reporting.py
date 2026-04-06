"""Reporting helpers for performance benchmark artifacts and charts."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, ScalarFormatter


@dataclass(frozen=True)
class DistributionSeries:
    metric_name: str
    unit: str
    bin_edges: list[float]
    counts: list[int]
    smoothed_counts: list[float]
    cumulative_counts: list[int]
    cumulative_percentages: list[float]
    sample_count: int
    percentiles: dict[str, float]

    @property
    def bin_midpoints(self) -> list[float]:
        return [(self.bin_edges[idx] + self.bin_edges[idx + 1]) / 2 for idx in range(len(self.counts))]

    @property
    def bin_width(self) -> float:
        if len(self.bin_edges) < 2:
            return 0.0
        return self.bin_edges[1] - self.bin_edges[0]


def calculate_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return math.nan
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * (percentile / 100.0)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] * (upper - index) + sorted_values[upper] * (index - lower)


def _format_y_axis(ax) -> None:
    formatter = ScalarFormatter(useOffset=False)
    formatter.set_scientific(False)
    ax.yaxis.set_major_formatter(formatter)


def _triangular_smooth(counts: Sequence[int]) -> list[float]:
    if not counts:
        return []
    weights = (1.0, 2.0, 3.0, 2.0, 1.0)
    smoothed: list[float] = []
    for index in range(len(counts)):
        weighted_total = 0.0
        weight_total = 0.0
        for offset, weight in zip(range(-2, 3), weights, strict=True):
            bucket = index + offset
            if bucket < 0 or bucket >= len(counts):
                continue
            weighted_total += counts[bucket] * weight
            weight_total += weight
        smoothed.append(weighted_total / weight_total if weight_total else 0.0)
    return smoothed


def prepare_distribution_series(
    *,
    metric_name: str,
    values: Sequence[float],
    unit: str = "ms",
    bin_count: int = 40,
) -> DistributionSeries:
    numeric_values = [float(value) for value in values if value is not None and not math.isnan(float(value))]
    if not numeric_values:
        return DistributionSeries(
            metric_name=metric_name,
            unit=unit,
            bin_edges=[0.0, 1.0],
            counts=[0],
            smoothed_counts=[0.0],
            cumulative_counts=[0],
            cumulative_percentages=[0.0],
            sample_count=0,
            percentiles={"median": math.nan, "p95": math.nan, "p99": math.nan},
        )

    minimum = min(numeric_values)
    maximum = max(numeric_values)
    if minimum == maximum:
        padding = max(1.0, abs(minimum) * 0.05)
        left_edge = max(0.0, minimum - padding)
        right_edge = maximum + padding
    else:
        padding = (maximum - minimum) * 0.03
        left_edge = max(0.0, minimum - padding)
        right_edge = maximum + padding

    step = (right_edge - left_edge) / bin_count
    if step <= 0:
        step = 1.0
        right_edge = left_edge + step * bin_count

    bin_edges = [left_edge + step * index for index in range(bin_count + 1)]
    counts = [0] * bin_count
    width = right_edge - left_edge
    for value in numeric_values:
        if width <= 0:
            bucket = 0
        else:
            relative = (value - left_edge) / width
            bucket = min(bin_count - 1, max(0, int(relative * bin_count)))
        counts[bucket] += 1

    cumulative_counts: list[int] = []
    running = 0
    for count in counts:
        running += count
        cumulative_counts.append(running)

    sample_count = len(numeric_values)
    cumulative_percentages = [(count / sample_count) * 100.0 for count in cumulative_counts]
    percentiles = {
        "median": calculate_percentile(numeric_values, 50),
        "p95": calculate_percentile(numeric_values, 95),
        "p99": calculate_percentile(numeric_values, 99),
    }
    return DistributionSeries(
        metric_name=metric_name,
        unit=unit,
        bin_edges=bin_edges,
        counts=counts,
        smoothed_counts=_triangular_smooth(counts),
        cumulative_counts=cumulative_counts,
        cumulative_percentages=cumulative_percentages,
        sample_count=sample_count,
        percentiles=percentiles,
    )


def write_distribution_csv(path: Path, series: DistributionSeries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "bin_index",
                f"bin_start_{series.unit}",
                f"bin_end_{series.unit}",
                f"bin_midpoint_{series.unit}",
                "count",
                "smoothed_count",
                "cumulative_count",
                "cumulative_percentage",
            ]
        )
        midpoints = series.bin_midpoints
        for index, count in enumerate(series.counts):
            writer.writerow(
                [
                    index,
                    f"{series.bin_edges[index]:.6f}",
                    f"{series.bin_edges[index + 1]:.6f}",
                    f"{midpoints[index]:.6f}",
                    count,
                    f"{series.smoothed_counts[index]:.6f}",
                    series.cumulative_counts[index],
                    f"{series.cumulative_percentages[index]:.6f}",
                ]
            )


def render_distribution_chart(
    *,
    path_without_suffix: Path,
    series: DistributionSeries,
    scenario_name: str,
    color: str,
    curve_color: str,
) -> dict[str, object]:
    path_without_suffix.parent.mkdir(parents=True, exist_ok=True)
    midpoints = series.bin_midpoints
    fig, ax = plt.subplots(figsize=(13, 7))
    fig.subplots_adjust(right=0.78, top=0.88)

    ax.bar(
        midpoints,
        series.counts,
        width=max(series.bin_width * 0.92, 0.001),
        color=color,
        edgecolor="#31445A",
        alpha=0.48,
        label="Histogram",
    )
    ax.plot(
        midpoints,
        series.smoothed_counts,
        color=curve_color,
        linewidth=2.6,
        label="Smoothed frequency",
    )

    percentile_colors = {
        "median": "#1F4E79",
        "p95": "#B3541E",
        "p99": "#8E1B1B",
    }
    for key in ("median", "p95", "p99"):
        value = series.percentiles[key]
        if math.isnan(value):
            continue
        ax.axvline(
            value,
            color=percentile_colors[key],
            linestyle="--",
            linewidth=2.0,
            alpha=0.9,
        )

    ax.set_xlabel(f"{series.metric_name} ({series.unit})")
    ax.set_ylabel("Request count")
    ax.set_title(f"{series.metric_name} Distribution")
    ax.text(
        0.0,
        1.03,
        f"{scenario_name} • n={series.sample_count}",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=11,
        color="#3E4B59",
    )
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper left")
    _format_y_axis(ax)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=8))

    annotation_lines = []
    for label in ("median", "p95", "p99"):
        value = series.percentiles[label]
        if math.isnan(value):
            continue
        annotation_lines.append(f"{label.upper():<6} {value:.2f} {series.unit}")
    ax.text(
        1.02,
        0.98,
        "\n".join(annotation_lines),
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        bbox={
            "boxstyle": "round,pad=0.5",
            "facecolor": "#F7F9FC",
            "edgecolor": "#CAD3DF",
            "alpha": 0.98,
        },
    )

    png_path = path_without_suffix.with_suffix(".png")
    svg_path = path_without_suffix.with_suffix(".svg")
    fig.tight_layout(rect=(0.0, 0.0, 0.78, 0.9))
    fig.savefig(png_path, dpi=180)
    fig.savefig(svg_path)
    plt.close(fig)

    return {
        "metric_name": series.metric_name,
        "sample_count": series.sample_count,
        "percentiles": dict(series.percentiles),
        "annotation_lines": annotation_lines,
        "png_path": str(png_path),
        "svg_path": str(svg_path),
    }


def generate_overview_charts(path: Path, detail_records: Sequence[Mapping[str, object]]) -> None:
    successful = [
        rec
        for rec in detail_records
        if rec.get("response_text")
        and isinstance(rec.get("total_latency_ms"), (int, float))
        and isinstance(rec.get("client_duration_ms"), (int, float))
    ]
    if successful:
        request_labels = [str(rec["request_id"]) for rec in successful]
        total_latencies = [float(rec["total_latency_ms"]) for rec in successful]
        ttfts = [float(rec["ttft_ms"]) if isinstance(rec.get("ttft_ms"), (int, float)) else 0.0 for rec in successful]
        client_durations = [float(rec["client_duration_ms"]) for rec in successful]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(request_labels, total_latencies, label="Total latency (ms)", color="#4C72B0")
        ax.bar(request_labels, ttfts, label="TTFT (ms)", color="#55A868")
        ax.set_xlabel("Request ID")
        ax.set_ylabel("Milliseconds")
        ax.set_title("Latency Breakdown (Successful Requests)")
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        _format_y_axis(ax)
        ax.tick_params(axis="x", labelbottom=False)
        fig.tight_layout()
        fig.savefig(path.with_suffix(".png"))
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(request_labels, client_durations, marker="o", linewidth=2, label="Client duration (ms)", color="#C44E52")
        ax.set_xlabel("Request ID")
        ax.set_ylabel("Milliseconds")
        ax.set_title("Client Duration per Successful Request")
        ax.grid(True, alpha=0.3)
        ax.legend()
        _format_y_axis(ax)
        ax.tick_params(axis="x", labelbottom=False)
        fig.tight_layout()
        fig.savefig(path.with_name(path.stem + "_client_duration.png"))
        plt.close(fig)

    scheduler_records = [
        rec
        for rec in detail_records
        if isinstance(rec.get("queue_wait_ms"), (int, float)) and isinstance(rec.get("processing_ms"), (int, float))
    ]
    if scheduler_records:
        scheduler_labels = [str(rec["request_id"]) for rec in scheduler_records]
        queue_waits = [float(rec["queue_wait_ms"]) for rec in scheduler_records]
        processing_times = [float(rec["processing_ms"]) for rec in scheduler_records]

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.bar(scheduler_labels, queue_waits, label="Queue wait (ms)", color="#8172B2")
        ax.bar(
            scheduler_labels,
            processing_times,
            bottom=queue_waits,
            label="Processing (ms)",
            color="#CCB974",
        )
        ax.set_xlabel("Request ID")
        ax.set_ylabel("Milliseconds")
        ax.set_title("Scheduler Queue + Processing")
        ax.legend()
        ax.grid(axis="y", alpha=0.3)
        _format_y_axis(ax)
        ax.tick_params(axis="x", labelbottom=False)
        fig.tight_layout()
        fig.savefig(path.with_name(path.stem + "_queue_processing.png"))
        plt.close(fig)

    success_times = []
    for rec in detail_records:
        status = rec.get("http_status")
        if not isinstance(status, int) or status >= 400:
            continue
        ts = rec.get("_response_ts") or rec.get("_request_ts")
        if ts is not None:
            success_times.append(ts)

    if success_times:
        success_times.sort()
        start_ts = success_times[0]
        elapsed_s = [(ts - start_ts).total_seconds() for ts in success_times]
        cumulative = list(range(1, len(elapsed_s) + 1))

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(elapsed_s, cumulative, marker="o", linewidth=2, color="#4C72B0")
        ax.set_xlabel("Time since first response (s)")
        ax.set_ylabel("Cumulative successful requests")
        ax.set_title("Cumulative Success Over Time")
        ax.grid(True, alpha=0.3)
        _format_y_axis(ax)
        ax.xaxis.set_major_locator(MaxNLocator(nbins=6))
        fig.tight_layout()
        fig.savefig(path.with_name(path.stem + "_cumulative_success.png"))
        plt.close(fig)
