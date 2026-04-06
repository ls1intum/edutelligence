import csv

import pytest

from tests.performance.reporting import (
    prepare_distribution_series,
    render_distribution_chart,
    write_distribution_csv,
)


def test_prepare_distribution_series_calculates_percentiles():
    series = prepare_distribution_series(metric_name="TTFT", values=[100, 200, 300, 400, 500], bin_count=5)

    assert series.sample_count == 5
    assert series.percentiles == pytest.approx({"median": 300.0, "p95": 480.0, "p99": 496.0})
    assert len(series.counts) == 5
    assert len(series.smoothed_counts) == 5


def test_distribution_csv_and_chart_are_written(tmp_path):
    series = prepare_distribution_series(metric_name="Total Latency", values=[1_000, 1_100, 1_200, 1_500, 2_000, 3_000], bin_count=6)
    csv_path = tmp_path / "latency_distribution.csv"
    chart_base = tmp_path / "latency_distribution"

    write_distribution_csv(csv_path, series)
    metadata = render_distribution_chart(
        path_without_suffix=chart_base,
        series=series,
        scenario_name="scenario-alpha",
        color="#7BA7D7",
        curve_color="#204B77",
    )

    with csv_path.open() as handle:
        rows = list(csv.DictReader(handle))

    assert csv_path.exists()
    assert chart_base.with_suffix(".png").exists()
    assert chart_base.with_suffix(".svg").exists()
    assert len(rows) == 6
    assert metadata["annotation_lines"] == [
        "MEDIAN 1350.00 ms",
        "P95    2750.00 ms",
        "P99    2950.00 ms",
    ]
    assert metadata["percentiles"] == pytest.approx({"median": 1350.0, "p95": 2750.0, "p99": 2950.0})
