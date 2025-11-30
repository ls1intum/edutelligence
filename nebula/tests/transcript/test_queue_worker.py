# tests/transcript/test_queue_worker.py
# pylint: disable=redefined-outer-name,unused-argument,missing-class-docstring,import-outside-toplevel,protected-access

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


@pytest.mark.anyio
async def test_cancel_job_in_queue_removes_it(monkeypatch):
    """Test that cancelling a job that's in the queue removes it."""
    monkeypatch.setattr(qw, "_job_queue", asyncio.Queue())

    # Don't actually start the worker, so jobs stay in queue
    req = TranscribeRequestDTO(
        videoUrl="https://example.com/video.m3u8", lectureUnitId=123
    )

    # Enqueue 3 jobs
    job_ids = ["job1", "job2", "job3"]
    for jid in job_ids:
        await qw.enqueue_job(jid, req)

    # Cancel the middle job
    result = await qw.cancel_job_processing("job2")

    # Check result
    assert result["status"] == "cancelled"
    assert "in queue" in result["message"]

    # Verify job2 is not in the queue anymore
    remaining_jobs = []
    while not qw._job_queue.empty():
        job_id, _ = await qw._job_queue.get()
        remaining_jobs.append(job_id)

    assert "job1" in remaining_jobs
    assert "job2" not in remaining_jobs
    assert "job3" in remaining_jobs


@pytest.mark.anyio
async def test_cancel_job_during_processing_stops_it(monkeypatch):
    """Test that cancelling a job during processing marks it for cancellation."""
    monkeypatch.setattr(qw, "_job_queue", asyncio.Queue())

    async def fake_heavy_pipeline(job_id, req):
        # Simulate being in processing
        await asyncio.sleep(0.01)

        # Check if cancelled
        from nebula.transcript.jobs import is_job_cancelled

        if await is_job_cancelled(job_id):
            raise asyncio.CancelledError("Job was cancelled")

        return {
            "transcription": {"segments": [{"start": 0.0, "end": 0.1, "text": "hi"}]},
            "video_path": "/tmp/video.mp4",
            "audio_path": "/tmp/audio.wav",
            "uid": "test-uid",
        }

    monkeypatch.setattr(qw, "_heavy_pipeline", fake_heavy_pipeline, raising=True)

    qw.start_worker()

    jid = "job-to-cancel"
    req = TranscribeRequestDTO(
        videoUrl="https://example.com/video.m3u8", lectureUnitId=123
    )
    await qw.enqueue_job(jid, req)

    # Wait a tiny bit for it to start processing
    await asyncio.sleep(0.05)

    # Cancel it
    result = await qw.cancel_job_processing(jid)

    # Should return cancellation result for processing job
    assert result["status"] == "cancelled"
    assert "processing" in result["message"]

    # Give it time to handle cancellation
    await asyncio.sleep(0.1)

    # Should have been marked as cancelled
    status = await get_job_status(jid)
    assert status["status"] == "cancelled"

    await qw.stop_worker()


@pytest.mark.anyio
async def test_remove_job_from_queue_returns_true_when_found(monkeypatch):
    """Test that remove_job_from_queue returns True when job is found."""
    monkeypatch.setattr(qw, "_job_queue", asyncio.Queue())

    req = TranscribeRequestDTO(
        videoUrl="https://example.com/video.m3u8", lectureUnitId=123
    )

    await qw.enqueue_job("job1", req)
    await qw.enqueue_job("job2", req)

    found = await qw.remove_job_from_queue("job1")
    assert found is True

    # Verify queue only has job2
    assert qw._job_queue.qsize() == 1
    remaining_job, _ = await qw._job_queue.get()
    assert remaining_job == "job2"


@pytest.mark.anyio
async def test_remove_job_from_queue_returns_false_when_not_found(monkeypatch):
    """Test that remove_job_from_queue returns False when job is not found."""
    monkeypatch.setattr(qw, "_job_queue", asyncio.Queue())

    req = TranscribeRequestDTO(
        videoUrl="https://example.com/video.m3u8", lectureUnitId=123
    )

    await qw.enqueue_job("job1", req)

    found = await qw.remove_job_from_queue("job2")
    assert found is False

    # Verify queue still has job1
    assert qw._job_queue.qsize() == 1


@pytest.mark.anyio
async def test_cancel_job_already_completed(monkeypatch):
    """Test cancelling a job that has already completed."""
    monkeypatch.setattr(qw, "_job_queue", asyncio.Queue())

    from nebula.transcript.jobs import create_job

    job_id = await create_job()
    await save_job_result(job_id, {"result": "done"})

    # Try to cancel the completed job
    result = await qw.cancel_job_processing(job_id)

    assert result["status"] == "cancelled"
    assert "may have already completed" in result["message"]


@pytest.mark.anyio
async def test_cleanup_temp_files_removes_files(monkeypatch, tmp_path):
    """Test that _cleanup_temp_files removes temporary files."""
    # Create fake temp files
    video_path = tmp_path / "video.mp4"
    audio_path = tmp_path / "audio.wav"
    chunk_dir = tmp_path / "chunks_test-uid"

    video_path.write_text("fake video")
    audio_path.write_text("fake audio")
    chunk_dir.mkdir()
    (chunk_dir / "chunk1.mp4").write_text("chunk")

    # Mock VIDEO_STORAGE_PATH to our tmp_path
    monkeypatch.setattr("nebula.transcript.queue_worker.VIDEO_STORAGE_PATH", tmp_path)

    # Call cleanup
    qw._cleanup_temp_files(str(video_path), str(audio_path), "test-uid")

    # Verify files are deleted
    assert not video_path.exists()
    assert not audio_path.exists()
    assert not chunk_dir.exists()


@pytest.mark.anyio
async def test_heavy_pipeline_checks_cancellation(monkeypatch):
    """Test that heavy pipeline checks for cancellation at multiple points."""
    from nebula.transcript.jobs import cancel_job

    job_id = "test-cancel-during-pipeline"
    req = TranscribeRequestDTO(
        videoUrl="https://example.com/video.m3u8", lectureUnitId=123
    )

    # Cancel the job before it starts
    await cancel_job(job_id)

    # Mock the heavy operations to never actually run
    async def fake_download(url, path):
        pass

    monkeypatch.setattr("nebula.transcript.queue_worker.download_video", fake_download)

    # Try to run the heavy pipeline
    try:
        await qw._heavy_pipeline(job_id, req)
        assert False, "Should have raised CancelledError"
    except asyncio.CancelledError:
        # Expected
        pass
