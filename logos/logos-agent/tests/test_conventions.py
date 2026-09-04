"""What every session is told, and who decides it.

The standing text is the part of an unattended agent most worth adjusting
after watching it work — and the part least worth waiting for a release to
adjust. It ships as a default in code and is overridable at runtime.
"""

from __future__ import annotations

import pytest
from app import conventions


@pytest.fixture(autouse=True)
def _clean():
    conventions.forget()
    yield
    conventions.forget()


def stored(monkeypatch, **row):
    async def get_instructions():
        return {"house_rules": None, "environment_notes": None, "updated_by": "", **row}

    monkeypatch.setattr(conventions.db, "get_instructions", get_instructions)


class TestReading:
    async def test_an_untouched_deployment_uses_what_it_ships_with(self, monkeypatch):
        async def nothing():
            return None

        monkeypatch.setattr(conventions.db, "get_instructions", nothing)

        text = await conventions.current()

        assert text.house_rules == conventions.HOUSE_RULES
        assert text.environment_notes == conventions.ENVIRONMENT_NOTES
        assert text.house_rules_default and text.environment_notes_default

    async def test_an_override_replaces_the_default(self, monkeypatch):
        stored(monkeypatch, house_rules="Be brief.", updated_by="tobias")

        text = await conventions.current()

        assert text.house_rules == "Be brief."
        assert not text.house_rules_default
        # The half nobody touched is still the shipped one.
        assert text.environment_notes == conventions.ENVIRONMENT_NOTES

    async def test_an_empty_override_is_a_decision_not_an_absence(self, monkeypatch):
        # "Say nothing here" is a thing an operator can mean.
        stored(monkeypatch, house_rules="")

        text = await conventions.current()

        assert text.house_rules == ""
        assert not text.house_rules_default

    async def test_an_unreadable_database_keeps_the_last_text(self, monkeypatch):
        stored(monkeypatch, house_rules="Be brief.")
        await conventions.current()

        async def broken():
            raise RuntimeError("connection refused")

        monkeypatch.setattr(conventions.db, "get_instructions", broken)
        conventions._read_at = 0.0

        # A session mid-flight must not suddenly be told something else
        # because a query failed.
        assert (await conventions.current()).house_rules == "Be brief."


class TestBuildingATask:
    async def test_the_conventions_follow_the_task(self, monkeypatch):
        stored(monkeypatch, house_rules="Be brief.")

        task = await conventions.for_task("Fix the alignment.")

        assert task == "Fix the alignment.\n\nBe brief."

    async def test_nothing_is_appended_when_there_is_nothing_to_say(self, monkeypatch):
        stored(monkeypatch, house_rules="   ")

        assert await conventions.for_task("Fix the alignment.") == "Fix the alignment."


class TestAReadThatWasOvertaken:
    """A save while a read is in flight must win.

    The cache holds for five seconds. A read that started before the save
    returns the old row, and putting that back in the cache means the page
    shows the new text while the next five seconds of sessions are built
    from the old one — with nothing anywhere saying so.
    """

    async def test_a_save_during_a_read_is_not_undone_by_it(self, monkeypatch):
        import asyncio

        released = asyncio.Event()

        async def slow_get_instructions():
            await released.wait()
            return {"house_rules": "the old text", "environment_notes": None, "updated_by": ""}

        async def set_instructions(**_kwargs):
            return None

        monkeypatch.setattr(conventions.db, "get_instructions", slow_get_instructions)
        monkeypatch.setattr(conventions.db, "set_instructions", set_instructions)

        reader = asyncio.create_task(conventions.current())
        await asyncio.sleep(0)

        # The save lands while the read above is still waiting.
        monkeypatch.setattr(
            conventions.db,
            "get_instructions",
            lambda: _answer({"house_rules": "the new text", "environment_notes": None, "updated_by": "tobias"}),
        )
        saved = await conventions.set_instructions(house_rules="the new text", by="tobias")
        released.set()
        await reader

        assert saved.house_rules == "the new text"
        # The overtaken read must not have put the old row back.
        assert (await conventions.current()).house_rules == "the new text"


async def _answer(row):
    return row
