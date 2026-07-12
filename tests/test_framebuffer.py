"""FramebufferDisplay tests against a mocked pygame module."""

import pytest
from PIL import Image

import pigauge.displays.framebuffer as framebuffer_module
from pigauge.displays.framebuffer import FramebufferDisplay

RESOLUTION = (800, 480)


class FakeSurface:
    def __init__(self):
        self.blits = []

    def blit(self, surface, position):
        self.blits.append((surface, position))


class FakePygame:
    """Just enough of the pygame API surface for the driver."""

    FULLSCREEN = 0x80000000

    def __init__(self):
        self.surface = FakeSurface()
        self.init_called = False
        self.quit_called = False
        self.set_mode_args = None
        self.flips = 0
        self.frombuffer_args = []
        self.mouse_visible = True

        fake = self

        class _Display:
            @staticmethod
            def init():
                fake.init_called = True

            @staticmethod
            def set_mode(resolution, flags):
                fake.set_mode_args = (resolution, flags)
                return fake.surface

            @staticmethod
            def flip():
                fake.flips += 1

            @staticmethod
            def quit():
                fake.quit_called = True

        class _ImageModule:
            @staticmethod
            def frombuffer(data, size, mode):
                fake.frombuffer_args.append((len(data), size, mode))
                return f"surface{len(fake.frombuffer_args)}"

        class _Mouse:
            @staticmethod
            def set_visible(visible):
                fake.mouse_visible = visible

        self.display = _Display()
        self.image = _ImageModule()
        self.mouse = _Mouse()


@pytest.fixture
def fake_pygame():
    return FakePygame()


def make_display(fake_pygame, **kwargs):
    kwargs.setdefault("sdl_driver", None)  # don't touch the dev environment
    return FramebufferDisplay(RESOLUTION, pygame_module=fake_pygame, **kwargs)


class TestInitialisation:
    def test_fullscreen_mode_set(self, fake_pygame):
        make_display(fake_pygame)
        assert fake_pygame.init_called
        assert fake_pygame.set_mode_args == (RESOLUTION, FakePygame.FULLSCREEN)
        assert fake_pygame.mouse_visible is False

    def test_windowed_mode_for_debugging(self, fake_pygame):
        make_display(fake_pygame, fullscreen=False)
        assert fake_pygame.set_mode_args == (RESOLUTION, 0)

    def test_sdl_driver_exported_when_requested(self, fake_pygame, monkeypatch):
        monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)
        FramebufferDisplay(RESOLUTION, pygame_module=fake_pygame, sdl_driver="kmsdrm")
        import os
        assert os.environ["SDL_VIDEODRIVER"] == "kmsdrm"
        monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)


class TestShow:
    def test_frame_converted_blitted_and_flipped(self, fake_pygame):
        display = make_display(fake_pygame)
        display.show(Image.new("RGB", RESOLUTION, "#102030"))
        assert fake_pygame.frombuffer_args == [(800 * 480 * 3, RESOLUTION, "RGB")]
        assert fake_pygame.surface.blits == [("surface1", (0, 0))]
        assert fake_pygame.flips == 1

    def test_wrong_frame_size_rejected(self, fake_pygame):
        display = make_display(fake_pygame)
        with pytest.raises(ValueError, match="does not match"):
            display.show(Image.new("RGB", (240, 240)))


class TestLifecycle:
    def test_close_quits_display(self, fake_pygame):
        display = make_display(fake_pygame)
        display.close()
        assert fake_pygame.quit_called

    def test_construction_without_pygame_gives_install_hint(self, monkeypatch):
        monkeypatch.setattr(framebuffer_module, "pygame", None)
        with pytest.raises(RuntimeError, match=r"pigauge\[pi\]"):
            FramebufferDisplay(RESOLUTION)
