"""The doorbell between writing an event and watching for one.

Watching an agent work is the one thing in this service that a person does
in real time. A stream that re-reads the database on a fixed tick puts a
floor under how live that can be, however fast everything else gets.
"""

from __future__ import annotations

import asyncio

from app import pulse


class TestWaiting:
    async def test_a_ring_before_the_wait_is_not_missed(self):
        pulse.forget(7)
        pulse.ring(7)

        # Would hang for the whole timeout if the bell only counted while
        # somebody was already listening.
        await asyncio.wait_for(pulse.wait(7, timeout=5.0), timeout=0.2)

    async def test_a_ring_during_the_wait_wakes_it(self):
        pulse.forget(7)
        loop = asyncio.get_running_loop()
        loop.call_later(0.02, pulse.ring, 7)

        started = loop.time()
        await pulse.wait(7, timeout=5.0)

        assert loop.time() - started < 1.0

    async def test_silence_ends_at_the_timeout(self):
        pulse.forget(7)

        # The fallback: a missed nudge costs a tick, not a stalled watcher.
        await asyncio.wait_for(pulse.wait(7, timeout=0.05), timeout=1.0)

    async def test_one_ring_wakes_one_wait(self):
        pulse.forget(7)
        pulse.ring(7)
        await pulse.wait(7, timeout=1.0)

        loop = asyncio.get_running_loop()
        started = loop.time()
        await pulse.wait(7, timeout=0.05)

        # The bell is cleared by the waiter it woke: a second wait must not
        # come straight back on the same ring and spin the stream.
        assert loop.time() - started >= 0.04

    async def test_sessions_do_not_share_a_bell(self):
        pulse.forget(7)
        pulse.forget(8)
        pulse.ring(8)

        loop = asyncio.get_running_loop()
        started = loop.time()
        await pulse.wait(7, timeout=0.05)

        assert loop.time() - started >= 0.04
