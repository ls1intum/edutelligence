"""The doorbell between writing an event and watching for one.

Watching an agent work is the one thing in this service that a person does
in real time. A stream that re-reads the database on a fixed tick puts a
floor under how live that can be, however fast everything else gets.

The bells themselves are the other half: every event write would otherwise
leave one behind for a session nobody is following, and a runner that runs
for weeks accumulates them.
"""

from __future__ import annotations

import asyncio

from app import pulse


class TestWaiting:
    async def test_a_ring_before_the_wait_is_not_missed(self):
        async with pulse.watching(7):
            pulse.ring(7)

            # Would wait out the whole timeout if the bell only counted
            # while somebody was already listening.
            await asyncio.wait_for(pulse.wait(7, timeout=5.0), timeout=0.2)

    async def test_a_ring_during_the_wait_wakes_it(self):
        loop = asyncio.get_running_loop()
        async with pulse.watching(7):
            loop.call_later(0.02, pulse.ring, 7)
            started = loop.time()

            await pulse.wait(7, timeout=5.0)

            assert loop.time() - started < 1.0

    async def test_silence_ends_at_the_timeout(self):
        async with pulse.watching(7):
            # The fallback: a missed nudge costs a tick, not a stalled
            # watcher.
            await asyncio.wait_for(pulse.wait(7, timeout=0.05), timeout=1.0)

    async def test_one_ring_wakes_one_wait(self):
        loop = asyncio.get_running_loop()
        async with pulse.watching(7):
            pulse.ring(7)
            await pulse.wait(7, timeout=1.0)
            started = loop.time()

            await pulse.wait(7, timeout=0.05)

            # The bell is cleared by the waiter it woke: a second wait must
            # not come straight back on the same ring and spin the stream.
            assert loop.time() - started >= 0.04

    async def test_sessions_do_not_share_a_bell(self):
        loop = asyncio.get_running_loop()
        async with pulse.watching(7), pulse.watching(8):
            pulse.ring(8)
            started = loop.time()

            await pulse.wait(7, timeout=0.05)

            assert loop.time() - started >= 0.04


class TestWhoIsListening:
    """Bells last exactly as long as somebody is following the session."""

    async def test_writing_to_a_session_nobody_watches_leaves_nothing(self):
        before = pulse.watched()

        # What the runner does thousands of times a day, almost always with
        # no browser open on that session.
        pulse.ring(4711)

        assert pulse.watched() == before

    async def test_a_watcher_registers_and_lets_go(self):
        before = pulse.watched()

        async with pulse.watching(7):
            assert pulse.watched() == before + 1

        assert pulse.watched() == before

    async def test_a_stream_that_drops_mid_connection_lets_go_too(self):
        before = pulse.watched()

        async def watcher():
            async with pulse.watching(7):
                await asyncio.sleep(30)

        task = asyncio.create_task(watcher())
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # The ordinary ending for a browser: the connection goes away
        # without the stream reaching a terminal state.
        assert pulse.watched() == before

    async def test_the_last_of_several_watchers_clears_it(self):
        before = pulse.watched()

        async with pulse.watching(7):
            async with pulse.watching(7):
                assert pulse.watched() == before + 1
            # One left, one still watching: the bell has to stay.
            assert pulse.watched() == before + 1
            pulse.ring(7)
            await asyncio.wait_for(pulse.wait(7, timeout=5.0), timeout=0.2)

        assert pulse.watched() == before

    async def test_waiting_without_a_bell_falls_back_to_the_timeout(self):
        loop = asyncio.get_running_loop()
        started = loop.time()

        await pulse.wait(4711, timeout=0.05)

        assert loop.time() - started >= 0.04
