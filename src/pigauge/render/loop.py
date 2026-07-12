"""Render loop: service every configured display from one thread.

Each display is bound to its own scene (built from its own layout file per
the ``displays:`` config section). The loop renders scene frames from the
latest bus values, optionally stamps an FPS overlay (``render.fps_overlay``
debug flag), shows them, and paces to ``target_fps``. It only ever reads
the bus — data acquisition stays in source threads (golden rule 5).
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from pigauge.core.config import AppConfig, load_gauge_layout, resolve_config_path
from pigauge.core.databus import DataBus
from pigauge.displays import Display, create_display
from pigauge.render.canvas import PillowCanvas
from pigauge.render.scene import GaugeScene

FPS_SMOOTHING = 0.2  # EMA weight for the displayed FPS figure
OVERLAY_POSITION = (4, 4)
OVERLAY_FONT_SIZE = 14
OVERLAY_COLOR = "#facc15"


@dataclass
class DisplayBinding:
    """One display paired with the scene that feeds it."""

    name: str
    display: Display
    scene: GaugeScene


def bindings_from_config(
    config: AppConfig, bus: DataBus, base_dir: str | Path | None = None
) -> list[DisplayBinding]:
    """Build every configured display with its own layout-backed scene."""
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    bindings = []
    for display_config in config.displays:
        display = create_display(display_config)
        layout = load_gauge_layout(resolve_config_path(display_config.layout, base))
        scene = GaugeScene(layout, bus)
        bindings.append(DisplayBinding(display_config.name, display, scene))
    return bindings


class RenderLoop:
    """Renders all bindings each frame; pacing optional (None = flat out)."""

    def __init__(
        self,
        bindings: list[DisplayBinding],
        target_fps: float | None = None,
        fps_overlay: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Bind displays to the loop; ``target_fps=None`` disables pacing."""
        self._bindings = bindings
        self._frame_period = None if target_fps is None else 1.0 / target_fps
        self._fps_overlay = fps_overlay
        self._clock = clock
        self._sleep = sleep
        self._stop_event = threading.Event()
        self._fps: dict[str, float] = {}
        self._last_shown: dict[str, float] = {}
        self.frame_counts: dict[str, int] = {binding.name: 0 for binding in bindings}

    @property
    def fps(self) -> dict[str, float]:
        """Smoothed frames-per-second per display name."""
        return dict(self._fps)

    def step(self) -> None:
        """Render and show one frame on every display."""
        for binding in self._bindings:
            frame = binding.scene.render()
            if self._fps_overlay:
                self._draw_overlay(frame, self._fps.get(binding.name, 0.0))
            binding.display.show(frame)
            self._record_shown(binding.name)

    def run(self, duration_s: float | None = None) -> None:
        """Loop until stop() (or ``duration_s`` elapses), pacing to target."""
        self._stop_event.clear()
        end_time = None if duration_s is None else self._clock() + duration_s
        while not self._stop_event.is_set():
            frame_started = self._clock()
            self.step()
            if end_time is not None and self._clock() >= end_time:
                return
            if self._frame_period is not None:
                remaining = self._frame_period - (self._clock() - frame_started)
                if remaining > 0:
                    self._sleep(remaining)

    def stop(self) -> None:
        """Make run() return after the current frame."""
        self._stop_event.set()

    def _record_shown(self, name: str) -> None:
        now = self._clock()
        previous = self._last_shown.get(name)
        self._last_shown[name] = now
        self.frame_counts[name] += 1
        if previous is None or now <= previous:
            return
        instantaneous = 1.0 / (now - previous)
        smoothed = self._fps.get(name)
        self._fps[name] = (
            instantaneous
            if smoothed is None
            else smoothed + FPS_SMOOTHING * (instantaneous - smoothed)
        )

    @staticmethod
    def _draw_overlay(frame: Image.Image, fps: float) -> None:
        """Stamp the achieved FPS in the frame corner (debug aid)."""
        ImageDraw.Draw(frame).text(
            OVERLAY_POSITION,
            f"{fps:.1f} FPS",
            fill=OVERLAY_COLOR,
            font=PillowCanvas.font(OVERLAY_FONT_SIZE),
            anchor="la",
        )
