"""Benchmark Runner: runs a test dataset against Iris and has every answer assessed.

Flow: load the dataset and its test cases by ID (Benchmark Data Service), get the answer of
Iris for each test case (Iris Response Service), assess each answer (Response Assessment
Service) and store both runs (Benchmark Data Service). A failing test case is recorded with
its error and does not stop the run.
"""

from datetime import datetime
from pathlib import Path

from ...database.benchmark_data_service import BenchmarkDataService
from ...iris.iris_response_service import IrisResponseService
from ..evaluator.response_assessment_service import ResponseAssessmentService
from ..models import BenchmarkRun, EvaluationRun, RunStatus, TestCaseResult


class BenchmarkRunner:
    def __init__(
        self,
        data: BenchmarkDataService,
        iris: IrisResponseService,
        assessor: ResponseAssessmentService,
        iris_name: str,
        judge_model: str,
    ):
        self.data = data
        self.iris = iris
        self.assessor = assessor
        self.iris_name = iris_name
        self.judge_model = judge_model

    def run(self, dataset_id: int) -> tuple[BenchmarkRun, EvaluationRun, Path]:
        dataset = self.data.get_test_dataset(dataset_id)
        started = datetime.now()
        benchmark_run = BenchmarkRun(
            id=f"{started:%Y%m%d-%H%M%S}-dataset{dataset.id}",
            dataset_id=dataset.id,
            dataset_version=dataset.version,
            iris=self.iris_name,
            started_at=started,
        )
        evaluation_run = EvaluationRun(
            benchmark_run_id=benchmark_run.id,
            judge_model=self.judge_model,
            started_at=started,
        )

        for test_case_id in dataset.test_case_ids:
            result = TestCaseResult(test_case_id=test_case_id)
            try:
                test_case = self.data.get_test_case(test_case_id)
                result.response = self.iris.get_response(test_case)
                evaluation_run.assessments.append(
                    self.assessor.assess(test_case, result.response)
                )
            except Exception as e:  # noqa: BLE001 - one failing test case must not stop the run
                result.error = f"{type(e).__name__}: {e}"
            benchmark_run.results.append(result)

        finished = datetime.now()
        for run in (benchmark_run, evaluation_run):
            run.finished_at = finished
            run.status = RunStatus.FINISHED
        folder = self.data.save_runs(benchmark_run, evaluation_run)
        return benchmark_run, evaluation_run, folder
