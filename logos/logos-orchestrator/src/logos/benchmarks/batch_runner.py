"""Sequential benchmark batches under one provider lease and cancellation handle."""

from collections.abc import Awaitable, Callable

from .configuration import BenchmarkBatch, BenchmarkRunSettings


async def run_benchmark_batch(
    batch: BenchmarkBatch,
    execute_run: Callable[[BenchmarkRunSettings, dict[str, int], bool], Awaitable[int | None]],
) -> None:
    """Stop on the first failed run; completed measurements remain stored."""
    total = len(batch.configurations) * batch.repetitions
    index = 0
    for configuration_index, settings in enumerate(batch.configurations, start=1):
        for repetition in range(1, batch.repetitions + 1):
            index += 1
            progress = {
                "run_index": index, "total_runs": total, "completed_runs": index - 1,
                "configuration_index": configuration_index, "repetition": repetition,
            }
            benchmark_id = await execute_run(settings, progress, index == total)
            if benchmark_id is None:
                return
