"""Benchmark Data Service: returns test datasets and test cases for given IDs.

The Benchmark Runner only knows IDs. Where the data comes from is hidden behind this
interface. For now a stub serves invented data from stub_data/; later an implementation
can read the (private, versioned) data repository instead.
"""

from pathlib import Path
from typing import Protocol

from ..evaluation_pipeline.models import TestCase, TestDataset


class BenchmarkDataService(Protocol):
    def get_test_dataset(self, dataset_id: int) -> TestDataset: ...

    def get_test_case(self, test_case_id: int) -> TestCase: ...


class StubBenchmarkDataService:
    """Serves invented example data. Contains no real student data."""

    def __init__(self, folder: Path = Path(__file__).parent / "stub_data"):
        self.folder = folder

    def get_test_dataset(self, dataset_id: int) -> TestDataset:
        return TestDataset.model_validate_json(self._read("test_datasets", dataset_id))

    def get_test_case(self, test_case_id: int) -> TestCase:
        return TestCase.model_validate_json(self._read("test_cases", test_case_id))

    def _read(self, kind: str, item_id: int) -> str:
        path = self.folder / kind / f"{item_id}.json"
        if not path.is_file():
            raise KeyError(f"unknown {kind[:-1].replace('_', ' ')} id: {item_id}")
        return path.read_text(encoding="utf-8")
