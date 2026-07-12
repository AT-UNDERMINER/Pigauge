"""Golden-image tests: fixed scenes with fixed data must not drift.

Fixtures live in tests/fixtures/golden/ and were approved by eye before
being locked in. Regenerate (only after re-approval!) with:

    python -m pigauge.tools.render_preview --layout <layout> [--stale] \
           --out tests/fixtures/golden/<name>.png

Comparison allows a small per-channel RMS difference so font rasteriser
drift across Pillow releases does not produce false failures, while layout
or colour regressions still do.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from pigauge.core.config import load_gauge_layout
from pigauge.render.scene import GaugeScene
from pigauge.tools.render_preview import simulated_bus

REPO_ROOT = Path(__file__).parent.parent
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"
SEED = 42          # must match render_preview defaults used to make fixtures
SIM_TIME_S = 12.0  # mid-acceleration: boost, rpm, and speed all in motion
RMS_TOLERANCE = 3.0

GOLDEN_CASES = {
    "single_round_boost": ("config/gauges/single_round_boost.yaml", False),
    "dash_800x480": ("config/gauges/dash_800x480.yaml", False),
    "single_round_boost_stale": ("config/gauges/single_round_boost.yaml", True),
}


def render_case(layout_path: str, stale: bool) -> Image.Image:
    layout = load_gauge_layout(REPO_ROOT / layout_path)
    scene = GaugeScene(layout, simulated_bus(SEED, SIM_TIME_S, stale=stale))
    return scene.render()


def max_channel_rms(a: Image.Image, b: Image.Image) -> float:
    return max(ImageStat.Stat(ImageChops.difference(a, b)).rms)


@pytest.mark.parametrize("name", sorted(GOLDEN_CASES))
def test_rendered_frame_matches_golden(name):
    layout_path, stale = GOLDEN_CASES[name]
    golden_file = GOLDEN_DIR / f"{name}.png"
    assert golden_file.is_file(), f"missing golden fixture {golden_file}"
    rendered = render_case(layout_path, stale)
    golden = Image.open(golden_file).convert("RGB")
    assert rendered.size == golden.size
    rms = max_channel_rms(rendered, golden)
    assert rms <= RMS_TOLERANCE, (
        f"{name} drifted from its golden fixture (max channel RMS {rms:.2f} > "
        f"{RMS_TOLERANCE}); if the change is intentional, re-render and re-approve"
    )


def test_stale_golden_differs_from_fresh_golden():
    """The stale fixture must actually exercise the greyed path."""
    fresh = Image.open(GOLDEN_DIR / "single_round_boost.png").convert("RGB")
    stale = Image.open(GOLDEN_DIR / "single_round_boost_stale.png").convert("RGB")
    assert max_channel_rms(fresh, stale) > RMS_TOLERANCE
