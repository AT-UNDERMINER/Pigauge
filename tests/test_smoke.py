"""Smoke tests: package imports and interface contracts exist (Phase 0 seed)."""

from pigauge.displays.base import Display
from pigauge.sources.base import Source, SourceStatus


def test_interfaces_are_abstract():
    import inspect
    assert inspect.isabstract(Source)
    assert inspect.isabstract(Display)


def test_source_status_states():
    assert {s.name for s in SourceStatus} == {"STOPPED", "CONNECTED", "RECONNECTING", "ERROR"}
