"""A dependency-free PNG decoder and colour histogram.

Why this exists rather than a dependency
----------------------------------------
`calm.zero_alarm_pixels` (Core 2 / Conformance 1) is specified as a PIXEL
SWEEP: "a rendered calm fixture, swept pixel-wise in both themes, contains no
`--alarm` or `--blocked` colour". A sweep needs the actual pixels, and
Playwright hands them over as PNG bytes. Pillow would decode them, but this
kit already carries one heavyweight test-only dependency (playwright, pinned
for reproducibility) and a second one buys nothing here: Chromium's own
encoder emits a narrow, well-specified subset -- 8-bit RGB or RGBA,
non-interlaced -- and that subset is ~80 lines of stdlib `zlib`.

Fails LOUD on anything outside that subset (`UnsupportedPng`). A decoder that
silently returned an empty pixel buffer for an unexpected colour type would
make every sweep report "zero alarm pixels" and pass forever, which is
precisely the hollow-green failure Freeze 3 exists to prevent.

The histogram, not a per-pixel scan
-----------------------------------
`histogram()` reduces an image to `{(r, g, b): count}` using strided `bytes`
slices and `collections.Counter`, so the hot loop runs in C rather than in
Python. Tolerance matching is then applied over the DISTINCT colours (a few
thousand on a real page) instead of over the millions of pixels, which is what
makes a full-page sweep at three viewports affordable in a test tier.
"""

from __future__ import annotations

import struct
import zlib
from collections import Counter
from dataclasses import dataclass

_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: bytes-per-pixel by PNG colour type, for the 8-bit subset we accept.
_CHANNELS = {2: 3, 6: 4}


class UnsupportedPng(Exception):
    """The PNG is outside the subset this decoder accepts.

    Never downgraded to "decode what we can": a partially-decoded image
    produces a partially-swept page, and a sweep that missed half the pixels
    reporting zero is indistinguishable from a calm page.
    """


@dataclass(frozen=True)
class Image:
    """Raw, unfiltered 8-bit pixel data plus the geometry to walk it."""

    width: int
    height: int
    channels: int  # 3 (RGB) or 4 (RGBA)
    pixels: bytes  # width * height * channels, row-major, no filter bytes

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode(data: bytes) -> Image:
    """Decode an 8-bit, non-interlaced RGB/RGBA PNG into raw pixels."""
    if not data.startswith(_SIGNATURE):
        raise UnsupportedPng("not a PNG: signature missing")

    idat = bytearray()
    header: tuple[int, int, int, int, int, int, int] | None = None
    pos = len(_SIGNATURE)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # 4 len + 4 type + length + 4 crc
        if ctype == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break

    if header is None:
        raise UnsupportedPng("no IHDR chunk")
    width, height, depth, colour_type, compression, filter_method, interlace = header
    if depth != 8:
        raise UnsupportedPng(f"bit depth {depth} (only 8 is supported)")
    if colour_type not in _CHANNELS:
        raise UnsupportedPng(f"colour type {colour_type} (only 2=RGB and 6=RGBA are supported)")
    if compression != 0 or filter_method != 0:
        raise UnsupportedPng(f"compression={compression} filter_method={filter_method}")
    if interlace != 0:
        raise UnsupportedPng("interlaced PNG (Adam7) is not supported")

    channels = _CHANNELS[colour_type]
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    expected = (stride + 1) * height
    if len(raw) != expected:
        raise UnsupportedPng(f"decompressed {len(raw)} bytes, expected {expected}")

    out = bytearray(stride * height)
    prev = bytes(stride)
    src = 0
    for y in range(height):
        ftype = raw[src]
        src += 1
        line = bytearray(raw[src : src + stride])
        src += stride
        if ftype == 0:
            pass
        elif ftype == 1:  # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif ftype == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                upper_left = prev[i - channels] if i >= channels else 0
                line[i] = (line[i] + _paeth(left, prev[i], upper_left)) & 0xFF
        else:
            raise UnsupportedPng(f"unknown filter type {ftype} on row {y}")
        out[y * stride : (y + 1) * stride] = line
        prev = bytes(line)

    return Image(width=width, height=height, channels=channels, pixels=bytes(out))


def histogram(image: Image) -> Counter[tuple[int, int, int]]:
    """`{(r, g, b): pixel_count}` for the whole image, alpha ignored.

    Alpha is dropped rather than composited because a page screenshot is
    already composited: Chromium hands back opaque pixels over the page's own
    background, which is exactly the surface an operator's eye receives.
    """
    px = image.pixels
    step = image.channels
    return Counter(zip(px[0::step], px[1::step], px[2::step], strict=True))


def count_near(
    hist: Counter[tuple[int, int, int]], target: tuple[int, int, int], *, tolerance: int
) -> int:
    """How many pixels sit within `tolerance` of `target` on every channel.

    Per-channel Chebyshev distance rather than Euclidean: a hue is "this
    colour, antialiased" when no channel has moved far, and that reading is
    the one that stays stable across a rendering-engine bump.
    """
    tr, tg, tb = target
    return sum(
        n
        for (r, g, b), n in hist.items()
        if abs(r - tr) <= tolerance and abs(g - tg) <= tolerance and abs(b - tb) <= tolerance
    )


def parse_hex(value: str) -> tuple[int, int, int]:
    """`"#f59e0b"` -> `(245, 158, 11)`."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {value!r}")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
