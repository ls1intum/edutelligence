"""Tests for the admission and yielding logic.

These are the decisions that keep the runner from stealing capacity out from
under users, so they are tested against payloads shaped like the orchestrator's
real `scheduler_state` response rather than against mocks of our own reading.
"""

from __future__ import annotations

import pytest
from app import capacity
from app.config import settings


def scheduler_state(models: list[dict], queue_total: int = 0) -> dict:
    """Build a payload in the orchestrator's debug_state() shape."""
    return {
        "queue_total": queue_total,
        "logosnode": {
            "providers": {
                "1": {
                    "name": "node-a",
                    "models": {str(i): m for i, m in enumerate(models)},
                }
            }
        },
    }


def loaded(active: int, capacity_: int, queue_depth: int = 0) -> dict:
    return {
        "model_name": "qwen",
        "active": active,
        "max_capacity": capacity_,
        "queue_depth": queue_depth,
        "loaded": True,
    }


class TestParseSchedulerState:
    def test_idle_fleet_reads_as_zero_load(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        assert reading.ok
        assert reading.load == 0.0
        assert reading.total_slots == 8
        assert reading.reclaimable is True

    def test_load_is_the_busy_share_of_loaded_slots(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(2, 8), loaded(2, 8)]))
        assert reading.load == pytest.approx(0.25)
        assert reading.busy_slots == 4
        assert reading.total_slots == 16

    def test_unloaded_models_contribute_no_capacity(self):
        # An unloaded model's slots do not exist yet. Counting them would make
        # a node with nothing resident look like a mostly-idle one.
        payload = scheduler_state([loaded(4, 4)])
        payload["logosnode"]["providers"]["1"]["models"]["9"] = {
            "model_name": "cold",
            "active": 0,
            "max_capacity": 32,
            "loaded": False,
        }
        reading = capacity.parse_scheduler_state(payload)
        assert reading.total_slots == 4
        assert reading.load == 1.0

    def test_nothing_resident_reads_as_idle_not_saturated(self):
        reading = capacity.parse_scheduler_state(scheduler_state([]))
        assert reading.ok
        assert reading.load == 0.0
        assert reading.total_slots == 0

    def test_empty_fleet_is_idle_but_not_reclaimable(self):
        # An empty fleet is not busy, but it has nothing idle to spend either:
        # starting a session there would warm a lane (demand created, not
        # capacity reclaimed), which is a separate, opt-in product decision.
        reading = capacity.parse_scheduler_state(scheduler_state([]))
        assert reading.reclaimable is False
        assert reading.detail == "no loaded models"

    def test_per_model_queue_depth_counts_towards_the_queue(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(1, 8, queue_depth=3)], queue_total=1))
        assert reading.queue_total == 4
        assert reading.saturated

    def test_active_above_capacity_cannot_exceed_full_load(self):
        # The orchestrator can briefly report more in flight than the declared
        # ceiling; a load above 1.0 would break every threshold comparison.
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(12, 8)]))
        assert reading.load == 1.0
        assert reading.busy_slots == 8


class TestStartDecision:
    def test_starts_when_idle(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_start, _ = capacity.start_decision(reading, running=0, paused=0)
        assert may_start

    def test_refuses_while_users_queue_even_if_slots_look_free(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)], queue_total=1))
        may_start, reason = capacity.start_decision(reading, running=0, paused=0)
        assert not may_start
        assert "queue" in reason

    def test_refuses_to_start_into_an_empty_fleet(self):
        reading = capacity.parse_scheduler_state(scheduler_state([]))
        may_start, reason = capacity.start_decision(reading, running=0, paused=0)
        assert not may_start
        assert "nothing to reclaim" in reason

    def test_refuses_above_the_start_threshold(self):
        busy = int(settings.start_below_load * 8) + 1
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(busy, 8)]))
        may_start, _ = capacity.start_decision(reading, running=0, paused=0)
        assert not may_start

    def test_refuses_at_the_parallel_ceiling(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_start, reason = capacity.start_decision(reading, running=settings.max_parallel_sessions, paused=0)
        assert not may_start
        assert "ceiling" in reason

    def test_paused_sessions_count_against_the_ceiling(self):
        # A paused session still holds a container and a workspace, so it must
        # occupy a slot; otherwise pausing would let the runner over-admit.
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_start, _ = capacity.start_decision(reading, running=0, paused=settings.max_parallel_sessions)
        assert not may_start

    def test_unknown_capacity_refuses_to_start(self):
        may_start, reason = capacity.start_decision(capacity.UNKNOWN, running=0, paused=0)
        assert not may_start
        assert "unknown" in reason


class TestPauseAndResume:
    def test_pauses_when_users_queue(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(1, 8)], queue_total=2))
        should_pause, _ = capacity.pause_decision(reading)
        assert should_pause

    def test_pauses_when_capacity_is_unknown(self):
        # Losing sight of the orchestrator while sessions run is exactly when
        # the cheapest thing to interrupt should be interrupted.
        should_pause, _ = capacity.pause_decision(capacity.UNKNOWN)
        assert should_pause

    def test_does_not_pause_a_quiet_fleet(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(1, 8)]))
        should_pause, _ = capacity.pause_decision(reading)
        assert not should_pause

    def test_resume_uses_the_start_threshold_not_the_pause_one(self):
        # Load between the two thresholds: no longer pause-worthy, but not yet
        # quiet enough to resume. Resuming here would pause again next tick.
        between = (settings.start_below_load + settings.pause_above_load) / 2
        slots = 100
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(int(between * slots), slots)]))
        assert not capacity.pause_decision(reading)[0]
        assert not capacity.resume_decision(reading)[0]

    def test_resumes_once_the_fleet_is_quiet(self):
        reading = capacity.parse_scheduler_state(scheduler_state([loaded(0, 8)]))
        may_resume, _ = capacity.resume_decision(reading)
        assert may_resume

    def test_does_not_resume_into_an_empty_fleet(self):
        # Resuming is admission too: a paused session would be the only thing
        # running on an empty fleet, so the same rule applies.
        reading = capacity.parse_scheduler_state(scheduler_state([]))
        may_resume, reason = capacity.resume_decision(reading)
        assert not may_resume
        assert "nothing to reclaim" in reason


class TestTheLaneWeAreServedBy:
    """The ratio has to be about the model a session will actually use.

    A fleet holds embedding models, rerankers and chat models that share
    nothing but a building. Summed together they answer a question nobody
    asked: "1 of 60 slots busy" says most of the fleet is asleep, not
    whether another agent session is safe to start.
    """

    # The lane the runner's key can reach: provider 15, model 97 — the
    # payload is keyed by those ids, and a name is not enough (the same
    # model is served by providers this key has no permission for).
    OURS = frozenset({("15", "97")})

    @staticmethod
    def fleet(*models, provider="15"):
        """A scheduler payload shaped like the orchestrator's own."""
        return {
            "queue_total": 0,
            "logosnode": {
                "providers": {
                    provider: {
                        "name": "deimama",
                        "models": {
                            str(model_id): {
                                "model_name": name,
                                "active": active,
                                "max_capacity": 20,
                                "queue_depth": 0,
                                "loaded": loaded,
                            }
                            for model_id, name, active, loaded in models
                        },
                    }
                }
            },
        }

    def test_only_our_own_deployment_counts(self):
        payload = self.fleet(
            (97, "Qwen/Qwen3.8-27B", 10, True),
            (38, "Qwen/Qwen3-Embedding-8B", 0, True),
            (37, "openai/gpt-oss-120b", 0, True),
        )

        reading = capacity.parse_scheduler_state(payload, lane=self.OURS)

        # 10 of our 20, not 10 of everybody's 60.
        assert reading.total_slots == 20
        assert reading.load == 0.5

    def test_the_same_model_on_a_provider_we_cannot_reach_does_not_count(self):
        # The point of matching ids rather than names: an idle provider the
        # key has no permission for would otherwise halve the load we read
        # and let a session start into a saturated lane.
        ours = self.fleet((97, "Qwen/Qwen3.8-27B", 20, True), provider="15")
        theirs = self.fleet((97, "Qwen/Qwen3.8-27B", 0, True), provider="61")
        ours["logosnode"]["providers"].update(theirs["logosnode"]["providers"])

        reading = capacity.parse_scheduler_state(ours, lane=self.OURS)

        assert reading.busy_slots == 20 and reading.total_slots == 20
        assert reading.load == 1.0

    def test_without_a_lane_the_fleet_is_the_answer(self):
        payload = self.fleet((97, "Qwen/Qwen3.8-27B", 10, True), (37, "openai/gpt-oss-120b", 0, True))

        reading = capacity.parse_scheduler_state(payload)

        assert reading.total_slots == 40

    def test_a_key_that_reaches_nothing_is_refused(self):
        # Not the same question as "no filter": there is no lane at all, so
        # a paused session must not be resumed into a permission the key no
        # longer has.
        payload = self.fleet((97, "Qwen/Qwen3.8-27B", 0, True))

        reading = capacity.parse_scheduler_state(payload, lane=frozenset())

        assert reading.reclaimable is False
        assert reading.load == 1.0

    def test_a_queue_anywhere_still_counts(self):
        # Models share GPUs: somebody waiting on another one is somebody
        # this runner should get out of the way of.
        payload = self.fleet((97, "Qwen/Qwen3.8-27B", 0, True), (37, "openai/gpt-oss-120b", 0, True))
        payload["logosnode"]["providers"]["15"]["models"]["37"]["queue_depth"] = 3

        reading = capacity.parse_scheduler_state(payload, lane=self.OURS)

        assert reading.queue_total == 3
        assert reading.saturated

    def test_a_sleeping_lane_falls_back_to_the_fleet(self):
        # Nothing of ours is resident, so there is nothing of ours to
        # measure — the fleet-wide ratio is the better of the two answers
        # available, and it is what this said before it knew about lanes.
        payload = self.fleet((97, "Qwen/Qwen3.8-27B", 0, False), (37, "openai/gpt-oss-120b", 15, True))

        reading = capacity.parse_scheduler_state(payload, lane=self.OURS)

        assert reading.busy_slots == 15 and reading.total_slots == 20
        assert "none of the runner" in reading.detail

    def test_a_cold_fleet_is_still_nothing_to_reclaim(self):
        payload = self.fleet((97, "Qwen/Qwen3.8-27B", 0, False), (37, "openai/gpt-oss-120b", 0, False))

        reading = capacity.parse_scheduler_state(payload, lane=self.OURS)

        # Starting here would load a model and occupy GPUs nobody was using,
        # which is the opposite of what this runner is for.
        assert reading.reclaimable is False

    def test_a_saturated_model_is_not_averaged_away(self):
        # A key permitted on two models: one full, one idle. A session bound
        # for the full one has nowhere to go, and the average would say the
        # lane is a fifth busy.
        payload = self.fleet((97, "Qwen/Qwen3.8-27B", 20, True), (37, "openai/gpt-oss-120b", 0, True))
        payload["logosnode"]["providers"]["15"]["models"]["37"]["max_capacity"] = 100

        reading = capacity.parse_scheduler_state(payload, lane=frozenset({("15", "97"), ("15", "37")}))

        assert reading.load == 1.0
        # And it says which model it is talking about.
        assert "Qwen/Qwen3.8-27B" in reading.detail


class TestWhatTheEngineSaysItself:
    """vLLM's own numbers, not the ledger's guess at them.

    In production a lane the orchestrator counted as serving two requests
    reported none running and an empty cache. The ledger is the one that
    cannot see inside the engine.
    """

    @staticmethod
    def one(**signals):
        return {
            "queue_total": 0,
            "logosnode": {
                "providers": {
                    "15": {
                        "models": {
                            "97": {
                                "model_name": "Qwen/Qwen3.8-27B",
                                "active": signals.pop("active", 0),
                                "queue_depth": signals.pop("queue_depth", 0),
                                "max_capacity": 20,
                                "loaded": True,
                                "scheduler_signals": signals,
                            }
                        }
                    }
                }
            },
        }

    LANE = frozenset({("15", "97")})

    def test_the_engine_outranks_the_ledger(self):
        # The ledger says two are in flight; the engine says none are.
        payload = self.one(active=2, requests_running_current=0.0, gpu_cache_usage_percent_avg=0.0)

        reading = capacity.parse_scheduler_state(payload, lane=self.LANE)

        assert reading.busy_slots == 0 and reading.load == 0.0

    def test_a_full_cache_stops_new_work(self):
        # Three of twenty "slots", and no room for a fourth: concurrency is
        # bounded by the cache, not by a number in a configuration file. It
        # is reported apart from the load, because the cache does not say
        # whose tokens are in it — a reason not to add, never a reason to
        # pause what is already running.
        payload = self.one(active=3, requests_running_current=3.0, gpu_cache_usage_percent_max=94.0)

        reading = capacity.parse_scheduler_state(payload, lane=self.LANE)

        assert reading.cache_pressure == 0.94
        assert "KV cache" in reading.detail
        assert not capacity.start_decision(reading, running=0, paused=0, max_parallel=4)[0]
        # And it does not pause anything: that would be the runner starving
        # itself for its own context.
        assert not capacity.pause_decision(reading)[0]

    def test_the_engine_s_queue_is_the_queue(self):
        payload = self.one(queue_depth=0, requests_running_current=20.0, queue_waiting_current=4.0)

        reading = capacity.parse_scheduler_state(payload, lane=self.LANE)

        assert reading.queue_total == 4 and reading.saturated

    def test_a_lane_that_reports_nothing_falls_back_to_the_ledger(self):
        # Not every provider reports engine signals; the ledger is still an
        # answer, just a worse one.
        payload = self.one(active=5, queue_depth=1)

        reading = capacity.parse_scheduler_state(payload, lane=self.LANE)

        assert reading.busy_slots == 5 and reading.queue_total == 1


class TestNotReactingToItself:
    """The orchestrator says how busy a model is, never who is keeping it so.

    A runner with sessions in flight reads its own requests as platform
    load: it pauses itself for them, the load it reacted to leaves with
    them, it resumes, and it does it again. Its own sessions queueing read
    as "users are queueing", which is the signal that means stop.
    """

    LANE = frozenset({("15", "97")})

    @staticmethod
    def busy(running: float, waiting: float = 0.0, name: str = "Qwen/Qwen3.8-27B", model_id: str = "97"):
        return {
            "queue_total": 0,
            "logosnode": {
                "providers": {
                    "15": {
                        "models": {
                            model_id: {
                                "model_name": name,
                                "active": 0,
                                "queue_depth": 0,
                                "max_capacity": 10,
                                "loaded": True,
                                "scheduler_signals": {
                                    "requests_running_current": running,
                                    "queue_waiting_current": waiting,
                                },
                            }
                        }
                    }
                }
            },
        }

    def test_our_own_requests_are_not_platform_load(self):
        reading = capacity.parse_scheduler_state(self.busy(3.0), lane=self.LANE, ours={"Qwen/Qwen3.8-27B": 3})

        assert reading.busy_slots == 0 and reading.load == 0.0

    def test_what_somebody_else_is_doing_remains(self):
        reading = capacity.parse_scheduler_state(self.busy(5.0), lane=self.LANE, ours={"Qwen/Qwen3.8-27B": 2})

        assert reading.busy_slots == 3 and reading.load == 0.3

    def test_our_own_queueing_is_not_a_user_waiting(self):
        reading = capacity.parse_scheduler_state(
            self.busy(2.0, waiting=1.0), lane=self.LANE, ours={"Qwen/Qwen3.8-27B": 3}
        )

        assert reading.queue_total == 0 and not reading.saturated

    def test_a_real_user_waiting_still_stops_it(self):
        reading = capacity.parse_scheduler_state(
            self.busy(2.0, waiting=3.0), lane=self.LANE, ours={"Qwen/Qwen3.8-27B": 3}
        )

        # One of those three waiting is ours; the other two are not.
        assert reading.queue_total == 2 and reading.saturated

    def test_sessions_on_another_model_are_not_subtracted_here(self):
        # The finding: eighteen user requests on one model and five agent
        # sessions on another would have read as an idle-looking lane.
        reading = capacity.parse_scheduler_state(self.busy(9.0), lane=self.LANE, ours={"some/other-model": 5})

        assert reading.busy_slots == 9 and reading.load == 0.9

    def test_nothing_of_ours_running_changes_nothing(self):
        reading = capacity.parse_scheduler_state(self.busy(4.0), lane=self.LANE)

        assert reading.busy_slots == 4


class TestWhichDecisionGetsTheDiscount:
    """Handing capacity back and taking more are different questions.

    Whether to pause is about other people: counting our own sessions there
    makes the runner stop for itself. Whether to admit is about the model:
    it does not matter who filled it, and our share is an estimate — a
    running session may be between turns, making no request at all.

    Both figures come from the same parsing, because the discount only means
    anything while the per-model numbers still exist.
    """

    LANE = frozenset({("15", "97"), ("15", "37")})

    @staticmethod
    def two_models(a_running: float, b_running: float, a_waiting: float = 0.0):
        def model(name, running, waiting):
            return {
                "model_name": name,
                "active": 0,
                "queue_depth": 0,
                "max_capacity": 10,
                "loaded": True,
                "scheduler_signals": {
                    "requests_running_current": running,
                    "queue_waiting_current": waiting,
                },
            }

        return {
            "queue_total": 0,
            "logosnode": {
                "providers": {
                    "15": {
                        "models": {
                            "97": model("model-a", a_running, a_waiting),
                            "37": model("model-b", b_running, 0.0),
                        }
                    }
                }
            },
        }

    def test_our_sessions_on_one_model_do_not_empty_another(self):
        # The finding: nine user requests on A and five runner sessions on
        # B read as 40% and stopped the runner from ever yielding.
        payload = self.two_models(a_running=9.0, b_running=5.0)

        adjusted = capacity.parse_scheduler_state(payload, lane=self.LANE, ours={"model-b": 5})

        assert adjusted.load == 0.9
        assert "model-a" in adjusted.detail

    def test_our_own_load_still_comes_off_its_own_model(self):
        payload = self.two_models(a_running=2.0, b_running=5.0)

        adjusted = capacity.parse_scheduler_state(payload, lane=self.LANE, ours={"model-b": 5})

        assert adjusted.load == 0.2

    def test_the_measured_figure_keeps_everything(self):
        payload = self.two_models(a_running=2.0, b_running=5.0)

        measured = capacity.parse_scheduler_state(payload, lane=self.LANE)

        # What admission decides on: it does not matter who filled the lane.
        assert measured.load == 0.5

    def test_a_user_waiting_behind_us_still_counts(self):
        payload = self.two_models(a_running=2.0, b_running=0.0, a_waiting=3.0)

        adjusted = capacity.parse_scheduler_state(payload, lane=self.LANE, ours={"model-a": 3})

        # Two of ours were serving, one of the three waiting is ours.
        assert adjusted.queue_total == 2 and adjusted.saturated

    def test_it_never_subtracts_more_than_is_there(self):
        payload = self.two_models(a_running=1.0, b_running=0.0)

        adjusted = capacity.parse_scheduler_state(payload, lane=self.LANE, ours={"model-a": 9})

        assert adjusted.busy_slots == 0 and adjusted.queue_total == 0
