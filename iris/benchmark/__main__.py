"""Command line entry point (stand-in for the Benchmark Control Center and CI).

Usage, from the iris/ folder:
    poetry run python -m benchmark run --dataset 1
"""

import argparse

from .database.benchmark_data_service import StubBenchmarkDataService
from .evaluation_pipeline.benchmark_runner.benchmark_runner import BenchmarkRunner
from .evaluation_pipeline.benchmark_runner.summary import format_summary
from .evaluation_pipeline.evaluator.response_assessment_service import (
    LlmJudgeAssessmentService,
)
from .iris.iris_response_service import StubIrisResponseService
from .logos.model_inference_service import StubModelInferenceService


def main() -> None:
    parser = argparse.ArgumentParser(prog="benchmark", description="Iris benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a test dataset against Iris and assess it")
    run.add_argument("--dataset", type=int, required=True, help="ID of the test dataset")
    run.add_argument("--data", choices=["stub"], default="stub", help="Benchmark Data Service")
    run.add_argument("--iris", choices=["stub"], default="stub", help="Iris Response Service")
    run.add_argument("--logos", choices=["stub"], default="stub", help="Model Inference Service")
    run.add_argument("--judge-model", default="stub-model", help="model used as judge")
    args = parser.parse_args()

    runner = BenchmarkRunner(
        data=StubBenchmarkDataService(),
        iris=StubIrisResponseService(),
        assessor=LlmJudgeAssessmentService(StubModelInferenceService(), args.judge_model),
        iris_name=args.iris,
        judge_model=args.judge_model,
    )
    benchmark_run, evaluation_run, folder = runner.run(args.dataset)
    print(format_summary(benchmark_run, evaluation_run))
    print(f"\nResults saved to {folder}")


if __name__ == "__main__":
    main()
