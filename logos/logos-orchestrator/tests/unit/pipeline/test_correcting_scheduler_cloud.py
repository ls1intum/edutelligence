"""Cloud peer provider type in ClassificationCorrectingScheduler.

A cloud peer is another Logos instance: same OpenAI surface, but its own
scheduling. From this side we don't reserve capacity and don't queue —
we always treat it as WARM and accept immediately.
"""

import pytest

from logos import (
    CLOUD_OVERHEAD_S,
    ReadinessTier,
    SchedulingRequest,
    estimate_ettft_cloud,
)
from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.queue import PriorityQueueManager


class _NoopLogosNodeFacade:
    def get_model_scheduler_view(self, model_id, provider_id):
        return None

    def get_model_name(self, model_id, provider_id):
        return None

    def get_provider_name(self, provider_id):
        return None

    def get_capacity_info(self, provider_id):
        raise KeyError(provider_id)

    def get_parallel_capacity(self, model_id, provider_id):
        raise KeyError((model_id, provider_id))

    def get_model_profiles(self, provider_id):
        return {}

    def get_all_lane_signals(self, provider_id):
        raise KeyError(provider_id)


class _NoopAzureFacade:
    def get_model_capacity(self, model_id, provider_id):
        return None

    def update_model_rate_limits(self, model_id, provider_id, headers):
        pass


def _make_scheduler():
    return ClassificationCorrectingScheduler(
        queue_manager=PriorityQueueManager(),
        logosnode_facade=_NoopLogosNodeFacade(),
        azure_facade=_NoopAzureFacade(),
        ettft_enabled=True,
    )


def test_estimate_ettft_cloud_is_warm():
    """estimate_ettft_cloud always returns a WARM tier with the baseline overhead."""
    est = estimate_ettft_cloud()
    assert est.tier == ReadinessTier.WARM
    assert est.expected_wait_s == CLOUD_OVERHEAD_S


def test_estimate_ettft_dispatches_to_cloud_branch():
    """provider_type='cloud' uses estimate_ettft_cloud (not the 'unknown' fallback)."""
    scheduler = _make_scheduler()
    est = scheduler._estimate_ettft(model_id=1, provider_id=20, provider_type="cloud")
    assert est.tier == ReadinessTier.WARM
    assert est.expected_wait_s == CLOUD_OVERHEAD_S


@pytest.mark.asyncio
async def test_cloud_candidate_selected_immediately():
    """A cloud candidate is accepted by _try_immediate_select with no queueing."""
    scheduler = _make_scheduler()

    candidates = [(1, 5.0, 1, 1)]
    deployments = [{"model_id": 1, "provider_id": 20, "type": "cloud"}]
    request = SchedulingRequest(
        request_id="req-cloud",
        classified_models=candidates,
        deployments=deployments,
        payload={},
    )

    result = await scheduler.schedule(request)

    assert result is not None
    assert result.provider_type == "cloud"
    assert result.model_id == 1
    assert result.provider_id == 20
    assert result.was_queued is False
