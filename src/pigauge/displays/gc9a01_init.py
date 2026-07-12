"""GC9A01 panel initialisation sequence.

The standard vendor bring-up used by the common open-source drivers
(Waveshare/Adafruit lineage): mostly undocumented manufacturer registers,
kept verbatim. Each entry is (command, data bytes, delay ms after send).
COLMOD is set to 16 bpp (RGB565) to match the driver's frame conversion.
"""

INIT_SEQUENCE: tuple[tuple[int, bytes, int], ...] = (
    (0xEF, b"", 0),
    (0xEB, b"\x14", 0),
    (0xFE, b"", 0),
    (0xEF, b"", 0),
    (0xEB, b"\x14", 0),
    (0x84, b"\x40", 0),
    (0x85, b"\xff", 0),
    (0x86, b"\xff", 0),
    (0x87, b"\xff", 0),
    (0x88, b"\x0a", 0),
    (0x89, b"\x21", 0),
    (0x8A, b"\x00", 0),
    (0x8B, b"\x80", 0),
    (0x8C, b"\x01", 0),
    (0x8D, b"\x01", 0),
    (0x8E, b"\xff", 0),
    (0x8F, b"\xff", 0),
    (0xB6, b"\x00\x00", 0),
    (0x3A, b"\x05", 0),  # COLMOD: 16 bits per pixel
    (0x90, b"\x08\x08\x08\x08", 0),
    (0xBD, b"\x06", 0),
    (0xBC, b"\x00", 0),
    (0xFF, b"\x60\x01\x04", 0),
    (0xC3, b"\x13", 0),
    (0xC4, b"\x13", 0),
    (0xC9, b"\x22", 0),
    (0xBE, b"\x11", 0),
    (0xE1, b"\x10\x0e", 0),
    (0xDF, b"\x21\x0c\x02", 0),
    (0xF0, b"\x45\x09\x08\x08\x26\x2a", 0),
    (0xF1, b"\x43\x70\x72\x36\x37\x6f", 0),
    (0xF2, b"\x45\x09\x08\x08\x26\x2a", 0),
    (0xF3, b"\x43\x70\x72\x36\x37\x6f", 0),
    (0xED, b"\x1b\x0b", 0),
    (0xAE, b"\x77", 0),
    (0xCD, b"\x63", 0),
    (0x70, b"\x07\x07\x04\x0e\x0f\x09\x07\x08\x03", 0),
    (0xE8, b"\x34", 0),
    (0x62, b"\x18\x0d\x71\xed\x70\x70\x18\x0f\x71\xef\x70\x70", 0),
    (0x63, b"\x18\x11\x71\xf1\x70\x70\x18\x13\x71\xf3\x70\x70", 0),
    (0x64, b"\x28\x29\xf1\x01\xf1\x00\x07", 0),
    (0x66, b"\x3c\x00\xcd\x67\x45\x45\x10\x00\x00\x00", 0),
    (0x67, b"\x00\x3c\x00\x00\x00\x01\x54\x10\x32\x98", 0),
    (0x74, b"\x10\x85\x80\x00\x00\x4e\x00", 0),
    (0x98, b"\x3e\x07", 0),
    (0x35, b"", 0),  # tearing effect line on
    (0x21, b"", 0),  # display inversion on (panel expects it)
    (0x11, b"", 120),  # sleep out, then mandatory settle
    (0x29, b"", 20),  # display on
)
