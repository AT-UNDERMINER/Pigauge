"""Shared fixtures. vcan tests auto-skip when vcan0 is absent."""

import pathlib

import pytest


def _vcan_available() -> bool:
    return pathlib.Path("/sys/class/net/vcan0").exists()


def pytest_runtest_setup(item):
    if "vcan" in item.keywords and not _vcan_available():
        pytest.skip("vcan0 not present (run scripts/vcan_up.sh)")
    if "hardware" in item.keywords:
        pytest.skip("hardware tests run manually on the Pi")
