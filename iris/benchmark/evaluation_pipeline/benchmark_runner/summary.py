"""Scores of a run for the command line.

Score per criterion = share of fulfilled ratings among the applicable ones:
yes = 1, to_some_extent = 0.5, no = 0; not_applicable is left out.
The overall score is the mean of the criterion scores.
"""

from ..evaluator.criteria import CRITERIA
from ..models import BenchmarkRun, EvaluationRun, Rating

POINTS = {Rating.YES: 1.0, Rating.TO_SOME_EXTENT: 0.5, Rating.NO: 0.0}


def criterion_scores(evaluation_run: EvaluationRun) -> dict[str, float | None]:
    points: dict[str, list[float]] = {c.id: [] for c in CRITERIA}
    for assessment in evaluation_run.assessments:
        for score in assessment.scores:
            if score.rating in POINTS:
                points.setdefault(score.criterion, []).append(POINTS[score.rating])
    return {cid: (sum(p) / len(p) if p else None) for cid, p in points.items()}


def format_summary(benchmark_run: BenchmarkRun, evaluation_run: EvaluationRun) -> str:
    total = len(benchmark_run.results)
    failed = [r for r in benchmark_run.results if r.error]
    scores = criterion_scores(evaluation_run)
    applicable = [s for s in scores.values() if s is not None]

    lines = [
        f"Benchmark run {benchmark_run.id}",
        f"Dataset {benchmark_run.dataset_id} (version {benchmark_run.dataset_version}), "
        f"Iris: {benchmark_run.iris}, judge: {evaluation_run.judge_model}",
        "",
        f"Test cases: {total}   answered and assessed: {len(evaluation_run.assessments)}   "
        f"failed: {len(failed)}",
        "",
        "Score per criterion (0-100 %):",
    ]
    names = {c.id: c.name for c in CRITERIA}
    for cid, score in scores.items():
        value = "n/a" if score is None else f"{score * 100:5.1f} %"
        lines.append(f"  {names.get(cid, cid):<40} {value}")
    overall = f"{sum(applicable) / len(applicable) * 100:.1f} %" if applicable else "n/a"
    lines += ["", f"Overall score: {overall}"]
    for r in failed:
        lines.append(f"  failed test case {r.test_case_id}: {r.error}")
    return "\n".join(lines)
