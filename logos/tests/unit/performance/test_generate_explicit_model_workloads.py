import csv
import json
import sys
from collections import Counter, defaultdict

from tests.performance.generate_explicit_model_workloads import (
    SCENARIO_BY_NAME,
    build_rows_for_scenario,
    main,
)
from tests.performance.workload_layouts import same_model_streaks


def _model_sequence(rows):
    ordered = sorted(rows, key=lambda row: (float(row["arrival_offset"]), row["request_id"]))
    return [json.loads(row["body_json"])["model"] for row in ordered]


def _minute_counts(rows):
    counts = Counter()
    for row in rows:
        counts[int(float(row["arrival_offset"])) // 60_000] += 1
    return counts


def _minute_model_counts(rows):
    counts = defaultdict(Counter)
    for row in rows:
        minute = int(float(row["arrival_offset"])) // 60_000
        model_name = json.loads(row["body_json"])["model"]
        counts[minute][model_name] += 1
    return counts


def test_bursty_600_scenario_has_exact_counts_and_burst_invariants():
    scenario = SCENARIO_BY_NAME["10m_local2_mistral_deepseek_bursty_600"]
    rows = build_rows_for_scenario(scenario)
    sequence = _model_sequence(rows)
    streak_sizes = [size for _, size in same_model_streaks(sequence)]

    assert len(rows) == 600
    assert Counter(sequence) == {
        "solidrust/Mistral-7B-Instruct-v0.3-AWQ": 319,
        "casperhansen/deepseek-r1-distill-llama-8b-awq": 281,
    }
    assert [count for _, count in sorted(_minute_counts(rows).items())] == [42, 78, 54, 66, 48, 84, 54, 72, 48, 54]
    assert min(int(float(row["arrival_offset"])) for row in rows) <= 5_000
    assert max(int(float(row["arrival_offset"])) for row in rows) >= 595_000
    assert min(streak_sizes) >= 4
    assert max(streak_sizes) <= 12


def test_bursty_2400_scenario_has_exact_counts_and_burst_invariants():
    scenario = SCENARIO_BY_NAME["10m_local2_mistral_deepseek_bursty_2400"]
    rows = build_rows_for_scenario(scenario)
    sequence = _model_sequence(rows)
    streak_sizes = [size for _, size in same_model_streaks(sequence)]

    assert len(rows) == 2400
    assert Counter(sequence) == {
        "solidrust/Mistral-7B-Instruct-v0.3-AWQ": 1277,
        "casperhansen/deepseek-r1-distill-llama-8b-awq": 1123,
    }
    assert [count for _, count in sorted(_minute_counts(rows).items())] == [168, 312, 216, 264, 192, 336, 216, 288, 192, 216]
    assert min(int(float(row["arrival_offset"])) for row in rows) <= 5_000
    assert max(int(float(row["arrival_offset"])) for row in rows) >= 595_000
    assert min(streak_sizes) >= 8
    assert max(streak_sizes) <= 24


def test_even_jittered_600_scenario_has_exact_time_and_model_spread():
    scenario = SCENARIO_BY_NAME["10m_local2_mistral_deepseek_even_jittered_600"]
    rows = build_rows_for_scenario(scenario)
    sequence = _model_sequence(rows)
    minute_model_counts = _minute_model_counts(rows)
    streak_sizes = [size for _, size in same_model_streaks(sequence)]

    assert len(rows) == 600
    assert Counter(sequence) == {
        "solidrust/Mistral-7B-Instruct-v0.3-AWQ": 300,
        "casperhansen/deepseek-r1-distill-llama-8b-awq": 300,
    }
    assert [count for _, count in sorted(_minute_counts(rows).items())] == [60] * 10
    assert all(
        model_counts == Counter(
            {
                "solidrust/Mistral-7B-Instruct-v0.3-AWQ": 30,
                "casperhansen/deepseek-r1-distill-llama-8b-awq": 30,
            }
        )
        for model_counts in minute_model_counts.values()
    )
    assert max(streak_sizes) <= 2
    assert min(int(float(row["arrival_offset"])) for row in rows) <= 5_000
    assert max(int(float(row["arrival_offset"])) for row in rows) >= 595_000


def test_even_jittered_2400_scenario_has_exact_time_and_model_spread():
    scenario = SCENARIO_BY_NAME["10m_local2_mistral_deepseek_even_jittered_2400"]
    rows = build_rows_for_scenario(scenario)
    sequence = _model_sequence(rows)
    minute_model_counts = _minute_model_counts(rows)
    streak_sizes = [size for _, size in same_model_streaks(sequence)]

    assert len(rows) == 2400
    assert Counter(sequence) == {
        "solidrust/Mistral-7B-Instruct-v0.3-AWQ": 1200,
        "casperhansen/deepseek-r1-distill-llama-8b-awq": 1200,
    }
    assert [count for _, count in sorted(_minute_counts(rows).items())] == [240] * 10
    assert all(
        model_counts == Counter(
            {
                "solidrust/Mistral-7B-Instruct-v0.3-AWQ": 120,
                "casperhansen/deepseek-r1-distill-llama-8b-awq": 120,
            }
        )
        for model_counts in minute_model_counts.values()
    )
    assert max(streak_sizes) <= 2
    assert min(int(float(row["arrival_offset"])) for row in rows) <= 5_000
    assert max(int(float(row["arrival_offset"])) for row in rows) >= 595_000


def test_main_supports_scenario_filter_and_writes_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_explicit_model_workloads.py",
            "--root",
            str(tmp_path),
            "--scenario",
            "10m_local2_mistral_deepseek_bursty_600",
        ],
    )

    assert main() == 0

    csv_path = tmp_path / "10m" / "workload_explicit_local2_mistral_deepseek_bursty_600_10m.csv"
    manifest_path = csv_path.with_suffix(".json")
    assert csv_path.exists()
    assert manifest_path.exists()

    with csv_path.open() as handle:
        rows = list(csv.DictReader(handle))
    manifest = json.loads(manifest_path.read_text())

    assert len(rows) == 600
    assert manifest["scenario_name"] == "10m_local2_mistral_deepseek_bursty_600"
    assert manifest["layout"] == "bursty"
