"""Poll scheduling: per-channel rates, priority order, no burst catch-up."""

import pytest

from pigauge.sources.obd_pids import decoder_for_pid
from pigauge.sources.obd_profile import PollEntry
from pigauge.sources.obd_scheduler import IDLE_WAIT_CAP_S, PollScheduler

RPM = PollEntry("engine.rpm", 0x0C, 10.0, decoder_for_pid(0x0C))
SPEED = PollEntry("vehicle.speed", 0x0D, 5.0, decoder_for_pid(0x0D))
COOLANT = PollEntry("engine.coolant_temp", 0x05, 1.0, decoder_for_pid(0x05))


def channel_ids(entries):
    return [entry.channel_id for entry in entries]


class TestPriorityOrder:
    def test_entries_sorted_fastest_first(self):
        scheduler = PollScheduler([COOLANT, RPM, SPEED])
        assert channel_ids(scheduler.entries) == [
            "engine.rpm", "vehicle.speed", "engine.coolant_temp"
        ]

    def test_due_list_keeps_priority_order(self):
        scheduler = PollScheduler([COOLANT, RPM, SPEED])
        assert channel_ids(scheduler.due(100.0))[0] == "engine.rpm"

    def test_equal_rates_break_ties_by_channel_id(self):
        fast_map = PollEntry("engine.map", 0x0B, 10.0, decoder_for_pid(0x0B))
        scheduler = PollScheduler([RPM, fast_map])
        assert channel_ids(scheduler.entries) == ["engine.map", "engine.rpm"]


class TestDueTiming:
    def test_everything_is_due_at_startup(self):
        scheduler = PollScheduler([RPM, COOLANT])
        assert len(scheduler.due(0.0)) == 2

    def test_polled_entry_not_due_until_its_period_elapses(self):
        scheduler = PollScheduler([RPM])
        scheduler.mark_polled([RPM], 100.0)
        assert scheduler.due(100.05) == []
        assert scheduler.due(100.1) == [RPM]

    def test_slow_channel_waits_while_fast_one_repeats(self):
        scheduler = PollScheduler([RPM, COOLANT])
        scheduler.mark_polled([RPM, COOLANT], 100.0)
        polls = 0
        for tick in range(1, 11):  # one second, 0.1 s steps
            now = 100.0 + tick * 0.1
            due = scheduler.due(now)
            polls += len(due)
            scheduler.mark_polled(due, now)
        assert polls == 11  # 10 x rpm + 1 x coolant

    def test_falling_behind_does_not_build_a_backlog(self):
        scheduler = PollScheduler([RPM])
        scheduler.mark_polled([RPM], 100.0)
        # link stalls for a second; the next poll re-bases from now
        scheduler.mark_polled(scheduler.due(101.0), 101.0)
        assert scheduler.due(101.05) == []

    def test_reset_makes_everything_due_again(self):
        scheduler = PollScheduler([RPM, COOLANT])
        scheduler.mark_polled([RPM, COOLANT], 100.0)
        scheduler.reset()
        assert len(scheduler.due(100.0)) == 2


class TestIdleWait:
    def test_zero_when_something_is_already_due(self):
        assert PollScheduler([RPM]).seconds_until_next(100.0) == 0.0

    def test_waits_until_the_next_due_entry(self):
        scheduler = PollScheduler([RPM])
        scheduler.mark_polled([RPM], 100.0)
        assert scheduler.seconds_until_next(100.02) == pytest.approx(0.08)

    def test_capped_so_stop_stays_responsive(self):
        scheduler = PollScheduler([COOLANT])
        scheduler.mark_polled([COOLANT], 100.0)
        assert scheduler.seconds_until_next(100.0) == IDLE_WAIT_CAP_S

    def test_empty_plan_waits_the_cap(self):
        assert PollScheduler([]).seconds_until_next(0.0) == IDLE_WAIT_CAP_S
