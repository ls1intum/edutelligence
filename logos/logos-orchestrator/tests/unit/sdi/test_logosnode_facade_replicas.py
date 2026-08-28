"""The facade's per-model replica counts (``models.replicas``).

The capacity planner asks the facade how many lanes of a model a worker may
run (``get_model_replicas``). The count travels with model registration —
refreshed declaratively through ``replace_registrations`` on every
``/internal/refresh_pipeline`` — and anything missing or malformed must
degrade to the historical single-lane behaviour, never break registration.
"""

from logos.queue import PriorityQueueManager
from logos.sdi.logosnode_facade import LogosNodeSchedulingDataFacade


def _facade() -> LogosNodeSchedulingDataFacade:
    return LogosNodeSchedulingDataFacade(PriorityQueueManager())


def _registration(model_id: int, model_name: str, *, replicas=None, provider_id=1):
    registration = {
        "provider_id": provider_id,
        "provider_name": "worker-a",
        "model_id": model_id,
        "model_name": model_name,
    }
    if replicas is not None:
        registration["replicas"] = replicas
    return registration


class TestGetModelReplicas:
    def test_unknown_model_reads_as_one(self):
        assert _facade().get_model_replicas("never-registered") == 1

    def test_register_model_stores_the_count(self):
        facade = _facade()
        facade.register_model(1, "worker-a", "http://fake", "org/model-a", 65536, provider_id=1, replicas=3)
        assert facade.get_model_replicas("org/model-a") == 3

    def test_register_model_without_count_falls_back_to_one(self):
        facade = _facade()
        facade.register_model(1, "worker-a", "http://fake", "org/model-a", 65536, provider_id=1)
        assert facade.get_model_replicas("org/model-a") == 1

    def test_malformed_counts_degrade_to_one(self):
        facade = _facade()
        facade.register_model(1, "worker-a", "http://fake", "a", 65536, provider_id=1, replicas=None)
        facade.register_model(2, "worker-a", "http://fake", "b", 65536, provider_id=1, replicas=0)
        facade.register_model(3, "worker-a", "http://fake", "c", 65536, provider_id=1, replicas="2")
        assert facade.get_model_replicas("a") == 1
        assert facade.get_model_replicas("b") == 1
        assert facade.get_model_replicas("c") == 2


class TestReplaceRegistrations:
    def test_replicas_follow_the_declarative_refresh(self):
        facade = _facade()
        facade.replace_registrations(
            [
                _registration(1, "org/model-a", replicas=4),
                _registration(2, "org/model-b"),
            ]
        )
        assert facade.get_model_replicas("org/model-a") == 4
        assert facade.get_model_replicas("org/model-b") == 1

    def test_the_refresh_replaces_stale_counts(self):
        """A refresh is declarative: a model dropped from the registration
        set must not keep serving its old count to the planner."""
        facade = _facade()
        facade.replace_registrations([_registration(1, "org/model-a", replicas=4)])
        facade.replace_registrations([_registration(2, "org/model-b", replicas=2)])
        assert facade.get_model_replicas("org/model-a") == 1
        assert facade.get_model_replicas("org/model-b") == 2

    def test_missing_or_malformed_values_degrade_to_one(self):
        facade = _facade()
        facade.replace_registrations(
            [
                _registration(1, "a"),
                _registration(2, "b", replicas=None),
                _registration(3, "c", replicas=0),
            ]
        )
        assert facade.get_model_replicas("a") == 1
        assert facade.get_model_replicas("b") == 1
        assert facade.get_model_replicas("c") == 1
