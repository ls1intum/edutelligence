# tests/transcript/test_queue_worker.py
# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel

import asyncio

import pytest

import nebula.transcript.queue_worker as qw  # use module so monkeypatching sticks
from nebula.transcript.dto import TranscribeRequestDTO
from nebula.transcript.jobs import fail_job, get_job_status, save_job_result


@pytest.mark.anyio
async def test_fifo_heavy_phase_order(monkeypatch):
    # Fresh queue bound to this loop
    monkeypatch.setattr(qw, "_job_queue", asyncio.Queue())

    processed_order = []
    done_events: dict[str, asyncio.Event] = {}

    async def fake_heavy_pipeline(job_id, req):
        processed_order.append(job_id)
        await asyncio.sleep(0.01)
        return {
            "transcription": {"segments": [{"start": 0.0, "end": 0.1, "text": "hi"}]},
            "video_path": "",
            "audio_path": "",
            "uid": "uid",
        }

    async def fake_light_phase(job_id, req, transcription, video_path, audio_path, uid):
        # mark result and signal completion
        await save_job_result(
            job_id, {"lectureUnitId": 123, "language": "en", "segments": []}
        )
        done_events[job_id].set()

    monkeypatch.setattr(qw, "_heavy_pipeline", fake_heavy_pipeline, raising=True)
    monkeypatch.setattr(qw, "_light_phase", fake_light_phase, raising=True)

    qw.start_worker()

    req = TranscribeRequestDTO(
        videoUrl="https://example.com/video.m3u8", lectureUnitId=123
    )
    jobs = ["job0", "job1", "job2"]

    # create per-job events BEFORE enqueue so the light phase can set them
    for jid in jobs:
        done_events[jid] = asyncio.Event()

    for jid in jobs:
        await qw.enqueue_job(jid, req)

    # wait for FIFO order to be observed (heavy phase)
    for _ in range(120):  # up to ~3s
        if processed_order == jobs:
            break
        await asyncio.sleep(0.025)
    assert processed_order == jobs

    # now wait for light phase to complete for each job deterministically
    await asyncio.wait_for(
        asyncio.gather(*(done_events[jid].wait() for jid in jobs)),
        timeout=5.0,
    )

    # final sanity: job store says done
    for jid in jobs:
        assert (await get_job_status(jid)).get("status") == "done"

    await qw.stop_worker()


@pytest.mark.anyio
async def test_light_phase_failure_marks_job_error(monkeypatch):
    monkeypatch.setattr(qw, "_job_queue", asyncio.Queue())

    async def fake_heavy_pipeline(job_id, req):
        return {
            "transcription": {"segments": [{"start": 0.0, "end": 0.1, "text": "hi"}]},
            "video_path": "",
            "audio_path": "",
            "uid": "uid",
        }

    async def fake_light_phase(job_id, req, transcription, video_path, audio_path, uid):
        # mark error explicitly instead of raising into the event loop
        await fail_job(job_id, "boom")

    monkeypatch.setattr(qw, "_heavy_pipeline", fake_heavy_pipeline, raising=True)
    monkeypatch.setattr(qw, "_light_phase", fake_light_phase, raising=True)

    qw.start_worker()
    jid = "job-error"
    req = TranscribeRequestDTO(
        videoUrl="https://example.com/video.m3u8", lectureUnitId=123
    )
    await qw.enqueue_job(jid, req)

    # Poll until state flips
    status = {}
    for _ in range(40):
        await asyncio.sleep(0.025)
        status = await get_job_status(jid)
        if status.get("status") in ("error", "done"):
            break

    assert status.get("status") == "error"
    assert "boom" in status.get("error", "")

    await qw.stop_worker()
