"""The pipeline hands the scheduler a stream identity, not just a payload.

Affinity keys are derived here rather than in the scheduler because this is
where the calling API key and the raw payload are both in hand.
"""

import pytest
from tests.unit.pipeline.test_pipeline_skip_classification import (
    _FakeContextResolver,
    _FakeMonitoring,
    _FakeScheduler,
    _RecordingClassifier,
)

from logos import PipelineRequest, RequestPipeline

DEPLOYMENTS = [{"model_id": 27, "provider_id": 12, "type": "logosnode"}]


def _payload(marker: str = "a"):
    return {
        "messages": [
            {"role": "system", "content": "You are a coding agent. " + "S" * 4000},
            {"role": "user", "content": f"{marker} " + "u" * 2000},
        ]
    }


def _pipeline():
    scheduler = _FakeScheduler()
    return (
        RequestPipeline(
            classifier=_RecordingClassifier(),
            scheduler=scheduler,
            executor=object(),
            context_resolver=_FakeContextResolver(),
            monitoring=_FakeMonitoring(),
        ),
        scheduler,
    )


async def _schedule(api_key_id, payload):
    pipeline, scheduler = _pipeline()
    await pipeline.process(
        PipelineRequest(
            payload=payload,
            headers={},
            allowed_models=[27],
            deployments=DEPLOYMENTS,
            policy=None,
            api_key_id=api_key_id,
        )
    )
    return scheduler.last_request


@pytest.mark.asyncio
async def test_affinity_keys_reach_the_scheduler():
    request = await _schedule(api_key_id=5, payload=_payload())
    assert request.affinity_keys


@pytest.mark.asyncio
async def test_identical_prompts_from_one_key_produce_the_same_keys():
    first = await _schedule(api_key_id=5, payload=_payload())
    second = await _schedule(api_key_id=5, payload=_payload())
    assert first.affinity_keys == second.affinity_keys


@pytest.mark.asyncio
async def test_the_same_prompt_under_two_keys_produces_different_keys():
    first = await _schedule(api_key_id=5, payload=_payload())
    second = await _schedule(api_key_id=6, payload=_payload())
    assert not set(first.affinity_keys) & set(second.affinity_keys)


@pytest.mark.asyncio
async def test_parallel_streams_under_one_key_stay_distinct():
    first = await _schedule(api_key_id=5, payload=_payload("stream-one"))
    second = await _schedule(api_key_id=5, payload=_payload("stream-two"))
    assert first.affinity_keys[0] != second.affinity_keys[0]


@pytest.mark.asyncio
async def test_a_request_without_an_api_key_carries_no_keys():
    request = await _schedule(api_key_id=None, payload=_payload())
    assert request.affinity_keys == []
