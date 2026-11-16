"""Benchmark Data Service: returns test data for given IDs and stores the results of runs.

The Benchmark Runner only knows IDs. Where the data comes from is hidden behind this
interface. For now a stub serves invented data from stub_data/ and writes results to local
files in runs/ (not versioned); later an implementation can use the private data repository
and a database instead.
"""

from pathlib import Path
from typing import Protocol

from ..evaluation_pipeline.models import BenchmarkRun, EvaluationRun, TestCase, TestDataset

BENCHMARK_FOLDER = Path(__file__).parent.parent


class BenchmarkDataService(Protocol):
    def get_test_dataset(self, dataset_id: int) -> TestDataset: ...

    def get_test_case(self, test_case_id: int) -> TestCase: ...

    def save_runs(self, benchmark_run: BenchmarkRun, evaluation_run: EvaluationRun) -> Path: ...


class StubBenchmarkDataService:
    """Serves invented example data. Contains no real student data."""

    def __init__(
        self,
        folder: Path = Path(__file__).parent / "stub_data",
        runs_folder: Path = BENCHMARK_FOLDER / "runs",
    ):
        self.folder = folder
        self.runs_folder = runs_folder

    def get_test_dataset(self, dataset_id: int) -> TestDataset:
        return TestDataset.model_validate_json(self._read("test_datasets", dataset_id))

    def get_test_case(self, test_case_id: int) -> TestCase:
        return TestCase.model_validate_json(self._read("test_cases", test_case_id))

    def save_runs(self, benchmark_run: BenchmarkRun, evaluation_run: EvaluationRun) -> Path:
        folder = self.runs_folder / benchmark_run.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "benchmark_run.json").write_text(
            benchmark_run.model_dump_json(indent=2), encoding="utf-8"
        )
        (folder / "evaluation_run.json").write_text(
            evaluation_run.model_dump_json(indent=2), encoding="utf-8"
        )
        return folder

    def _read(self, kind: str, item_id: int) -> str:
        path = self.folder / kind / f"{item_id}.json"
        if not path.is_file():
            raise KeyError(f"unknown {kind[:-1].replace('_', ' ')} id: {item_id}")
        return path.read_text(encoding="utf-8")
