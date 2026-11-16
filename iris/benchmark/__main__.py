"""Command line entry point (stand-in for the Benchmark Control Center and CI).

Usage, from the iris/ folder:
    poetry run python -m benchmark run --dataset 1
    poetry run python -m benchmark run --dataset 1 --iris pyris   (Pyris must be running)
    poetry run python -m benchmark run --dataset 1 --iris pyris --logos logos

The Logos API key is read from benchmark/.env (LOGOS_API_KEY=..., not versioned, see
.env.example). An environment variable of the same name takes precedence, e.g. in CI.
"""

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from .database.benchmark_data_service import StubBenchmarkDataService
from .evaluation_pipeline.benchmark_runner.benchmark_runner import BenchmarkRunner
from .evaluation_pipeline.benchmark_runner.summary import format_summary
from .evaluation_pipeline.evaluator.response_assessment_service import (
    LlmJudgeAssessmentService,
)
from .iris.iris_response_service import PyrisIrisResponseService, StubIrisResponseService
from .logos.model_inference_service import (
    LOGOS_URL,
    LogosModelInferenceService,
    StubModelInferenceService,
)

DEFAULT_JUDGE_MODEL = "openai/gpt-oss-120b"  # local model on Logos, differs from Iris' model


def main() -> None:
    load_dotenv(Path(__file__).parent / ".env", override=False)
    parser = argparse.ArgumentParser(prog="benchmark", description="Iris benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a test dataset against Iris and assess it")
    run.add_argument("--dataset", type=int, required=True, help="ID of the test dataset")
    run.add_argument("--data", choices=["stub"], default="stub", help="Benchmark Data Service")
    run.add_argument("--iris", choices=["stub", "pyris"], default="stub", help="Iris Response Service")
    run.add_argument("--logos", choices=["stub", "logos"], default="stub", help="Model Inference Service")
    run.add_argument(
        "--judge-model",
        default=None,
        help=f"model used as judge (default with --logos logos: {DEFAULT_JUDGE_MODEL})",
    )
    run.add_argument("--logos-url", default=LOGOS_URL)

    pyris = run.add_argument_group("Pyris (only with --iris pyris)")
    pyris.add_argument("--pyris-url", default="http://localhost:8000")
    pyris.add_argument(
        "--pyris-token",
        default=os.environ.get("PYRIS_API_TOKEN", "secret"),
        help="API token from application.local.yml (default: $PYRIS_API_TOKEN or 'secret')",
    )
    pyris.add_argument("--timeout", type=float, default=300, help="seconds to wait per test case")
    pyris.add_argument("--variant", default="default")
    pyris.add_argument("--support-level", choices=["low", "moderate", "high"], default="moderate")
    pyris.add_argument("--selection", choices=["CLOUD_AI", "LOCAL_AI"], default="CLOUD_AI")
    args = parser.parse_args()

    if args.iris == "pyris":
        iris = PyrisIrisResponseService(
            args.pyris_url,
            args.pyris_token,
            timeout=args.timeout,
            variant=args.variant,
            support_level=args.support_level,
            selection=args.selection,
        )
        iris_name = f"pyris {args.pyris_url} (variant {args.variant}, {args.selection}, support {args.support_level})"
    else:
        iris = StubIrisResponseService()
        iris_name = "stub"

    if args.logos == "logos":
        # the key comes from benchmark/.env or the environment, never from the repository
        inference = LogosModelInferenceService(os.environ.get("LOGOS_API_KEY", ""), args.logos_url)
        judge_model = args.judge_model or DEFAULT_JUDGE_MODEL
    else:
        inference = StubModelInferenceService()
        judge_model = args.judge_model or "stub-model"

    runner = BenchmarkRunner(
        data=StubBenchmarkDataService(),
        iris=iris,
        assessor=LlmJudgeAssessmentService(inference, judge_model),
        iris_name=iris_name,
        judge_model=judge_model,
    )
    try:
        benchmark_run, evaluation_run, folder = runner.run(args.dataset)
    finally:
        if isinstance(iris, PyrisIrisResponseService):
            iris.close()
    print(format_summary(benchmark_run, evaluation_run))
    print(f"\nResults saved to {folder}")


if __name__ == "__main__":
    main()
