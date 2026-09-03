"""Tests for the two things an operator can change while the runner runs.

Both matter during an incident, which is exactly when nobody wants to edit
an `.env` on a host and restart a service that is in the middle of ten
sessions.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from app import capacity, controls


@pytest.fixture(autouse=True)
def _clean():
    controls.forget()
    yield
    controls.forget()


def stored(monkeypatch, **row):
    async def get_controls():
        return {"mode": "running", "mode_reason": "", "max_parallel": None, "updated_by": "", **row}

    monkeypatch.setattr(controls.db, "get_controls", get_controls)


class TestReading:
    async def test_an_untouched_runner_uses_its_configuration(self, monkeypatch):
        async def nothing():
            return None

        monkeypatch.setattr(controls.db, "get_controls", nothing)

        state = await controls.current()

        assert not state.paused
        assert state.max_parallel == controls.settings.max_parallel_sessions
        assert state.admission_block() == ""

    async def test_a_pause_is_read_with_its_reason(self, monkeypatch):
        stored(monkeypatch, mode="paused", mode_reason="incident 4711", updated_by="tobias")

        state = await controls.current()

        assert state.paused
        assert "incident 4711" in state.admission_block()

    async def test_a_lowered_ceiling_wins_over_the_configuration(self, monkeypatch):
        stored(monkeypatch, max_parallel=2)

        state = await controls.current()

        assert state.max_parallel == 2
        assert state.max_parallel_override == 2

    async def test_a_ceiling_of_zero_blocks_admission_without_pausing(self, monkeypatch):
        # Draining: nothing new starts, what runs keeps running.
        stored(monkeypatch, max_parallel=0)

        state = await controls.current()

        assert not state.paused
        assert "zero" in state.admission_block()

    async def test_a_reading_is_reused_for_a_moment(self, monkeypatch):
        calls: list = []

        async def counting():
            calls.append(1)
            return {"mode": "running", "mode_reason": "", "max_parallel": None, "updated_by": ""}

        monkeypatch.setattr(controls.db, "get_controls", counting)

        await controls.current()
        await controls.current()

        # The scheduler asks on every pass and every decision; one query per
        # couple of seconds is the point of the cache.
        assert len(calls) == 1

    async def test_an_unreadable_database_does_not_forget_a_pause(self, monkeypatch):
        stored(monkeypatch, mode="paused", mode_reason="incident")
        await controls.current()

        async def broken():
            raise RuntimeError("connection refused")

        monkeypatch.setattr(controls.db, "get_controls", broken)
        controls._read_at = 0.0  # force a re-read

        state = await controls.current()

        # A pause is an operator's intent; forgetting it because of a
        # transient error is the wrong way to fail.
        assert state.paused


class TestTheTwoHalvesOfTheSwitch:
    async def test_draining_stops_new_work_but_not_the_running_kind(self, monkeypatch):
        stored(monkeypatch, mode="draining", mode_reason="before a deploy")

        state = await controls.current()

        # Nothing new starts…
        assert "no new sessions" in state.admission_block()
        # …and what is under way is left alone, which is the whole
        # difference between draining and pausing.
        assert state.may_resume() is True
        assert state.paused is False

    async def test_pausing_also_takes_back_what_is_running(self, monkeypatch):
        stored(monkeypatch, mode="paused", mode_reason="incident")

        state = await controls.current()

        assert state.paused is True
        assert state.may_resume() is False

    async def test_an_unknown_mode_is_read_as_running(self, monkeypatch):
        # A value the database should not hold must not silently stop the
        # runner, nor silently un-stop it: 'running' is what the schema's
        # own default says.
        stored(monkeypatch, mode="halted")

        assert (await controls.current()).mode == "running"


class TestWriting:
    async def test_stopping_stores_the_reason_and_the_person(self, monkeypatch):
        written: list = []

        async def set_controls(**kwargs):
            written.append(kwargs)

        async def get_controls():
            return {"mode": "paused", "mode_reason": "incident", "max_parallel": None, "updated_by": "tobias"}

        monkeypatch.setattr(controls.db, "set_controls", set_controls)
        monkeypatch.setattr(controls.db, "get_controls", get_controls)

        state = await controls.set_mode(mode="paused", reason="incident", by="tobias")

        assert written[0]["mode"] == "paused"
        assert written[0]["mode_reason"] == "incident"
        assert written[0]["updated_by"] == "tobias"
        assert state.paused

    async def test_running_again_clears_the_reason(self, monkeypatch):
        written: list = []

        async def set_controls(**kwargs):
            written.append(kwargs)

        async def get_controls():
            return {"mode": "running", "mode_reason": "", "max_parallel": None, "updated_by": "tobias"}

        monkeypatch.setattr(controls.db, "set_controls", set_controls)
        monkeypatch.setattr(controls.db, "get_controls", get_controls)

        await controls.set_mode(mode="running", reason="", by="tobias")

        assert written[0]["mode_reason"] == ""

    async def test_an_unknown_mode_is_refused(self, monkeypatch):
        with pytest.raises(ValueError, match="unknown mode"):
            await controls.set_mode(mode="halted", reason="", by="tobias")

    async def test_clearing_the_ceiling_is_not_the_same_as_zero(self, monkeypatch):
        written: list = []

        async def set_controls(**kwargs):
            written.append(kwargs)

        async def get_controls():
            return {"mode": "running", "mode_reason": "", "max_parallel": None, "updated_by": ""}

        monkeypatch.setattr(controls.db, "set_controls", set_controls)
        monkeypatch.setattr(controls.db, "get_controls", get_controls)

        await controls.set_max_parallel(limit=None, by="tobias")
        await controls.set_max_parallel(limit=0, by="tobias")

        assert written[0]["clear_max_parallel"] is True
        assert written[1]["clear_max_parallel"] is False and written[1]["max_parallel"] == 0


class TestAdmission:
    def test_the_ceiling_in_force_is_the_one_that_decides(self):
        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=10, queue_total=0, ok=True)

        may_start, why = capacity.start_decision(reading, running=2, paused=0, max_parallel=2)

        assert not may_start and "2/2" in why

    def test_a_ceiling_of_zero_says_so(self):
        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=10, queue_total=0, ok=True)

        may_start, why = capacity.start_decision(reading, running=0, paused=0, max_parallel=0)

        assert not may_start and "zero" in why

    def test_without_an_override_the_configuration_applies(self, monkeypatch):
        monkeypatch.setattr(capacity, "settings", replace(capacity.settings, max_parallel_sessions=3))
        reading = capacity.Reading(load=0.0, busy_slots=0, total_slots=10, queue_total=0, ok=True)

        assert capacity.start_decision(reading, running=3, paused=0)[0] is False
        assert capacity.start_decision(reading, running=2, paused=0)[0] is True
