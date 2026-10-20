"""ClassificationCorrectingScheduler.try_reroute only moves a request to a ready deployment."""

from types import SimpleNamespace

from logos.pipeline.correcting_scheduler import ClassificationCorrectingScheduler
from logos.pipeline.ettft_estimator import ReadinessTier
from logos.pipeline.scheduler_interface import SchedulingRequest, SchedulingResult

MODEL_ID = 31
STUCK = 1
SLEEPING_ELSEWHERE = 2
WARM = 3


class _Facade:
    def get_model_name(self, model_id, provider_id):  # noqa: ARG002
        return "embed"

    def get_provider_name(self, provider_id):
        return f"worker-{provider_id}"


def _ettft(tier):
    return SimpleNamespace(tier=tier, ettft_ms=0.0, warmth_state=0, expected_wait_s=0.0)


def _scheduler(scored):
    scheduler = ClassificationCorrectingScheduler.__new__(ClassificationCorrectingScheduler)
    scheduler._logosnode = _Facade()
    scheduler.calls = {"scores": [], "released": [], "selected": []}

    def compute(candidates, deployments, affinity=None, input_tokens=0, request_id=None):  # noqa: ARG001
        scheduler.calls["scores"].append([d["provider_id"] for d in deployments])
        return [s for s in scored if s[1] in {d["provider_id"] for d in deployments}]

    def select(ready, request_id):  # noqa: ARG001
        scheduler.calls["selected"].append([s[1] for s in ready])
        return ready[0] if ready else None

    def release(model_id, provider_id, provider_type, request_id):  # noqa: ARG001
        scheduler.calls["released"].append((model_id, provider_id))

    def create(model_id, provider_id, provider_type, priority_int, request_id, was_queued, api_key_id=None):
        return SchedulingResult(
            model_id=model_id,
            provider_id=provider_id,
            provider_type=provider_type,
            queue_entry_id=None,
            was_queued=was_queued,
            queue_depth_at_schedule=0,
        )

    scheduler._compute_candidate_scores = compute
    scheduler._try_immediate_select = select
    scheduler.release = release
    scheduler._create_result = create
    return scheduler


def _request(providers, required_provider_id=None):
    return SchedulingRequest(
        request_id="req-1",
        payload={"input": "x"},
        deployments=[{"model_id": MODEL_ID, "provider_id": p, "type": "logosnode"} for p in providers],
        classified_models=[(MODEL_ID, 1.0, 1)],
        required_provider_id=required_provider_id,
    )


def test_moves_to_a_warm_deployment_and_releases_the_stuck_one():
    scored = [
        (MODEL_ID, SLEEPING_ELSEWHERE, "logosnode", 1.0, 1, _ettft(ReadinessTier.SLEEPING)),
        (MODEL_ID, WARM, "logosnode", 0.9, 1, _ettft(ReadinessTier.WARM)),
    ]
    scheduler = _scheduler(scored)

    result = scheduler.try_reroute(_request([STUCK, SLEEPING_ELSEWHERE, WARM]), MODEL_ID, STUCK)

    assert result is not None and result.provider_id == WARM
    # The stuck provider is never a candidate, and a sleeping one is skipped.
    assert scheduler.calls["scores"] == [[SLEEPING_ELSEWHERE, WARM]]
    assert scheduler.calls["selected"] == [[WARM]]
    assert scheduler.calls["released"] == [(MODEL_ID, STUCK)]


def test_keeps_the_reservation_when_nothing_is_ready():
    scored = [(MODEL_ID, SLEEPING_ELSEWHERE, "logosnode", 1.0, 1, _ettft(ReadinessTier.SLEEPING))]
    scheduler = _scheduler(scored)

    assert scheduler.try_reroute(_request([STUCK, SLEEPING_ELSEWHERE]), MODEL_ID, STUCK) is None
    assert scheduler.calls["released"] == []


def test_never_moves_a_request_bound_to_its_provider():
    scheduler = _scheduler([(MODEL_ID, WARM, "logosnode", 1.0, 1, _ettft(ReadinessTier.WARM))])

    assert scheduler.try_reroute(_request([STUCK, WARM], required_provider_id=STUCK), MODEL_ID, STUCK) is None
    assert scheduler.calls["scores"] == []


def test_no_other_deployment_means_no_reroute():
    scheduler = _scheduler([])

    assert scheduler.try_reroute(_request([STUCK]), MODEL_ID, STUCK) is None
    assert scheduler.calls["released"] == []


def test_a_full_alternative_keeps_the_original_reservation():
    # The warm deployment passes the readiness check but has no free slot by
    # the time it is reserved. The request must still hold its original
    # reservation, or it would later be forwarded without capacity accounting.
    scheduler = _scheduler([(MODEL_ID, WARM, "logosnode", 1.0, 1, _ettft(ReadinessTier.WARM))])
    scheduler._try_immediate_select = lambda ready, request_id: None  # noqa: ARG005

    assert scheduler.try_reroute(_request([STUCK, WARM]), MODEL_ID, STUCK) is None
    assert scheduler.calls["released"] == []
