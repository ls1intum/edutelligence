"""Replay captured vLLM failures and assert the worker's verdict and its action.

This is the suite's compatibility oracle. Each entry in
``harness/corpus/manifest.yaml`` is a startup failure that happened (or that a
fingerprint in ``vllm_process.py`` was written for), paired with what the worker
must conclude. The log travels the real path — fake vLLM stdout →
``_stream_logs`` → the 200-line ``_recent_logs`` deque → the classifiers — so a
change that breaks the plumbing fails here too, not only a change to a pattern.

Classification alone is not enough, so the recovery action is asserted next to
it: a fatal CUDA error must not purge caches, a poisoned cache must purge and
retry exactly once, a rejected checkpoint must be discarded and recorded, and a
benign failure must do none of those things. False positives are the expensive
direction — widening a fingerprint to catch an unrelated startup failure wipes
every model's compile cache on the node.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from harness import corpus
from harness import lane as lane_harness
from harness.gpusim.scenario import GpuScenario, VllmScript

ENTRIES = corpus.load()
UNSHARDED = [e for e in ENTRIES if not e.sharded]
SHARDED = [e for e in ENTRIES if e.sharded]
POISONED = [e for e in ENTRIES if e.expect.poisoned_cache]
BENIGN = [e for e in ENTRIES if e.benign]

SHARDED_COMPLETION_MARKER = ".logos_sharded_complete"


def _ids(entries):
    return [e.id for e in entries]


def seed_compile_cache(handle, config) -> Path:
    """Leave behind the compile cache a previous *healthy* start would have.

    The environment fingerprint matters: a cache dir with no ``cache_meta.json``
    is wiped proactively at the top of every spawn (the worker cannot tell
    whether it came from this build), which would mask whatever the test is
    actually asking about. Stamping it through the worker's own writer makes the
    seeded cache indistinguishable from a real one.

    Only ``torch_compile_cache/`` and ``rank_*/`` are purge targets;
    ``modelinfos/`` deliberately survives, so it is seeded too and asserted on.
    """
    lane_dir = Path(handle._lane_compile_cache_dir(config))
    for sub in ("torch_compile_cache", "rank_0_0", "modelinfos"):
        target = lane_dir / sub
        target.mkdir(parents=True, exist_ok=True)
        (target / "artifact.bin").write_bytes(b"compiled")
    handle._write_lane_cache_meta(config)
    handle._write_compile_cache_stamp()
    return lane_dir


def seed_sharded_checkpoint(cache_root: Path, model: str, tp: int) -> Path:
    """Place a conversion the worker will treat as ready to serve.

    Cheaper than running a real conversion and equivalent from the lane's point
    of view: ``_maybe_prepare_sharded_checkpoint`` only checks for the
    completion marker before serving the directory with
    ``--load-format sharded_state``.
    """
    from logos_worker_node import sharded_checkpoint as sc

    target = sc.sharded_checkpoint_dir(str(cache_root / "cache"), model, tp)
    target.mkdir(parents=True, exist_ok=True)
    (target / "model-rank-0-part-0.safetensors").write_bytes(b"shard")
    (target / SHARDED_COMPLETION_MARKER).write_text(f"model={model}\ntp={tp}\n", encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", UNSHARDED, ids=_ids(UNSHARDED))
async def test_corpus_entry_is_classified_as_the_manifest_says(entry, gpu_sim, lane):
    gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(emit_log=entry.log, exit_code=1))

    async with lane() as handle:
        error = await lane_harness.try_spawn(handle, lane_harness.lane_config())

        assert error is not None, f"{entry.id} is a startup failure but the lane came up"

        assert handle.has_fatal_cuda_errors is entry.expect.fatal_cuda, (
            f"{entry.id}: has_fatal_cuda_errors={handle.has_fatal_cuda_errors}, "
            f"manifest says {entry.expect.fatal_cuda} — {entry.summary}"
        )
        assert handle.has_poisoned_compile_cache is entry.expect.poisoned_cache, (
            f"{entry.id}: has_poisoned_compile_cache={handle.has_poisoned_compile_cache}, "
            f"manifest says {entry.expect.poisoned_cache} — {entry.summary}"
        )
        assert handle._matched_cache_poisoning_fingerprint() == entry.expect.cache_fingerprint, (
            f"{entry.id}: matched fingerprint "
            f"{handle._matched_cache_poisoning_fingerprint()!r}, "
            f"manifest says {entry.expect.cache_fingerprint!r}"
        )


def test_every_corpus_log_is_classified():
    """An unlisted log file is an uncovered failure mode hiding in plain sight."""
    orphans = corpus.orphan_logs()
    assert not orphans, f"corpus log(s) missing from manifest.yaml: {orphans}"


def test_every_known_fingerprint_has_a_corpus_entry():
    """Each fingerprint in the worker must be pinned by at least one log.

    Without this, a fingerprint can be added, silently stop matching, and never
    fire again in production — the failure mode that is hardest to notice.
    """
    from logos_worker_node.vllm_process import VllmProcessHandle

    known = {name for name, _fragments in VllmProcessHandle._CACHE_POISONING_FINGERPRINTS}
    covered = {e.expect.cache_fingerprint for e in ENTRIES if e.expect.cache_fingerprint}
    assert known <= covered, f"fingerprint(s) with no corpus entry: {sorted(known - covered)}"


# ---------------------------------------------------------------------------
# Recovery actions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", POISONED, ids=_ids(POISONED))
async def test_poisoned_cache_is_purged_and_retried_exactly_once(entry, gpu_sim, cache_root, lane):
    """One purge, one retry, then propagate — never a purge/retry loop."""
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(emit_log=entry.log, exit_code=1))
    config = lane_harness.lane_config()

    async with lane() as handle:
        lane_dir = seed_compile_cache(handle, config)
        error = await lane_harness.try_spawn(handle, config)

        assert error is not None
        assert not (lane_dir / "torch_compile_cache").exists(), "the poisoned compile artifacts survived the purge"
        assert not (lane_dir / "rank_0_0").exists(), "the poisoned rank cache survived the purge"
        assert (lane_dir / "modelinfos").exists(), (
            "modelinfos/ was purged — it is not implicated in cache poisoning and " "is expensive to rebuild"
        )
        assert (
            len(env.invocations()) == 2
        ), f"expected spawn + one retry after the purge, got {len(env.invocations())} invocation(s)"


async def test_repeat_poisoning_within_the_hour_is_not_purged_again(gpu_sim, lane):
    """The purge budget is one per (model, hour), and it survives new handles.

    Without the cap, a model whose startup is broken for a non-cache reason —
    but whose traceback happens to name a cache path — loops purge → retry →
    fail forever, rebuilding the compile cache on every attempt. The ledger is
    module-level precisely so a lane-manager restart cannot reset it, so the
    second lane here gets a fresh handle on purpose.
    """
    env = gpu_sim(
        GpuScenario.homogeneous("l40s", 1),
        VllmScript(emit_log="compile_cache_stack_trace.log", exit_code=1),
    )
    config = lane_harness.lane_config()

    async with lane(lane_id="lane-first") as handle:
        seed_compile_cache(handle, config)
        assert await lane_harness.try_spawn(handle, config) is not None
    first_round = len(env.invocations())
    assert first_round == 2, "the first poisoning should purge and retry once"

    async with lane(lane_id="lane-second") as handle:
        seed_compile_cache(handle, config)
        assert await lane_harness.try_spawn(handle, config) is not None

    assert (
        len(env.invocations()) - first_round == 1
    ), "a second poisoning of the same model within the hour purged and retried again"


@pytest.mark.parametrize("entry", BENIGN, ids=_ids(BENIGN))
async def test_benign_failure_triggers_no_recovery(entry, gpu_sim, cache_root, lane):
    """A startup failure that no recovery can fix must not trigger one.

    Purging here would cost every model on the node a full recompile, for a
    problem that is a bad token, a typo, or hardware the model cannot run on.
    """
    env = gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(emit_log=entry.log, exit_code=1))
    config = lane_harness.lane_config()

    async with lane() as handle:
        lane_dir = seed_compile_cache(handle, config)
        error = await lane_harness.try_spawn(handle, config)

        assert error is not None
        assert (lane_dir / "torch_compile_cache").exists(), f"{entry.id} wrongly purged the compile cache"
        assert (lane_dir / "rank_0_0").exists(), f"{entry.id} wrongly purged the rank cache"
        assert len(env.invocations()) == 1, f"{entry.id} wrongly retried the spawn"


@pytest.mark.parametrize("entry", SHARDED, ids=_ids(SHARDED))
async def test_rejected_sharded_checkpoint_is_discarded_and_retried_unsharded(entry, gpu_sim, cache_root, lane):
    """A conversion the loader refuses must not be served — or rebuilt — again.

    The conversion completes, writes its marker, and looks ready forever after;
    only a lane trying to serve it finds out. Without the discard this is a
    permanent outage of one model, reported as nothing more than a failed
    add_lane.
    """
    # The failing spawn serves shards; the retry must fall back to the full
    # checkpoint, so only the first invocation may carry --load-format.
    env = gpu_sim(
        GpuScenario.homogeneous("l40s", 2),
        VllmScript(emit_log=entry.log, exit_code=1),
    )
    config = lane_harness.lane_config(tensor_parallel_size=2)
    sharded_dir = seed_sharded_checkpoint(cache_root, config.model, 2)

    async with lane() as handle:
        error = await lane_harness.try_spawn(handle, config)

        assert error is not None
        assert not (
            sharded_dir / SHARDED_COMPLETION_MARKER
        ).exists(), "the rejected checkpoint still looks ready — the next spawn will serve it again"

        invocations = env.invocations()
        assert (
            len(invocations) == 2
        ), f"expected the sharded spawn plus one full-checkpoint retry, got {len(invocations)}"
        assert "--load-format" in invocations[0]["argv"], "the first spawn did not serve the sharded checkpoint"
        assert (
            "--load-format" not in invocations[1]["argv"]
        ), "the retry rebuilt the same unusable shards instead of serving the full checkpoint"


async def test_fatal_cuda_error_does_not_purge_the_compile_cache(gpu_sim, cache_root, lane):
    """A wedged GPU is not a cache problem; purging would destroy work for nothing."""
    env = gpu_sim(
        GpuScenario.homogeneous("l40s", 1),
        VllmScript(emit_log="cuda_devices_busy.log", exit_code=1),
    )
    config = lane_harness.lane_config()

    async with lane() as handle:
        lane_dir = seed_compile_cache(handle, config)
        error = await lane_harness.try_spawn(handle, config)

        assert error is not None
        assert handle.has_fatal_cuda_errors
        assert (lane_dir / "torch_compile_cache").exists()
        assert len(env.invocations()) == 1


async def test_failure_logs_are_persisted_for_postmortem(gpu_sim, lane, monkeypatch, tmp_path):
    """The captured log has to outlive the process that produced it.

    Without this the only record of a startup failure is whatever the worker's
    own stdout buffer still holds by the time someone looks.
    """
    tmp_path / "vllm-logs"
    monkeypatch.setattr("logos_worker_node.vllm_process.Path", Path)
    gpu_sim(GpuScenario.homogeneous("l40s", 1), VllmScript(emit_log="cuda_devices_busy.log", exit_code=1))

    async with lane() as handle:
        await lane_harness.try_spawn(handle, lane_harness.lane_config())
        handle.persist_recent_logs("e2e_corpus")

    written = sorted(Path("/tmp/logos-vllm-logs").glob(f"{handle.lane_id}_*_e2e_corpus.log"))
    assert written, "no failure log was persisted"
    assert "all CUDA-capable devices are busy or unavailable" in written[-1].read_text()
    for path in written:
        os.unlink(path)
