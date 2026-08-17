#!/usr/bin/env python3
"""Generate the work-tracker's PWA icon PNGs (`pwa-192.png`, `pwa-512.png`,
`apple-touch-icon.png`) and write them into
`src/amplifier_work_tracker/webassets/` -- the same "real file, read once at
import time" convention `webtheme.py` already uses for its two embedded
fonts (`_FONTS_DIR` / `_font_b64`), applied here to bytes that must be
independently fetchable HTTP resources (a manifest icon URL, an
`apple-touch-icon` link) rather than inlined into CSS.

Run this manually whenever the mark needs to change:

    python3 scripts/gen_pwa_icons.py

Requires Pillow. Deliberately NOT a runtime (or even `dev`/`web` extra)
dependency of this package -- icon generation is a one-time/occasional
build step the maintainer runs locally, not something the running
dashboard, its tests, or its CI needs. Install it ad hoc to regenerate:
`pip install --user Pillow` (or use any Python that already has it).

THE MARK: three horizontal bars of decreasing length, rounded caps, in the
app's amber accent (`--amber` / `#D9A253` in `webtheme.CSS`) on the app's
charcoal ground (`--ground` / `#0D0D0C`) -- a direct, deliberate echo of the
dashboard's own "workspace by state" bar and ready-queue-by-age bars (see
`webapp.py`'s module docstring), not a generic checkmark or clip-art glyph.
Kept within a safe-zone box so the 512px maskable variant survives
Android's circular crop without clipping (Android keeps roughly the inner
80% circle of a maskable icon; this mark's content sits within ~72% of the
canvas, centered, for margin).
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw

GROUND = (0x0D, 0x0D, 0x0C, 255)  # webtheme.CSS's --ground
AMBER = (0xD9, 0xA2, 0x53, 255)  # webtheme.CSS's --amber
AMBER_DIM_1 = (0xBF, 0x8F, 0x4A, 255)  # one step dimmer, for bar 2
AMBER_DIM_2 = (0xA3, 0x7A, 0x42, 255)  # dimmer still, for bar 3

OUT_DIR = pathlib.Path(__file__).parent.parent / "src" / "amplifier_work_tracker" / "webassets"


def _draw_mark(size: int) -> Image.Image:
    # Pillow's bundled type stubs declare `new(...)`'s `color` param as
    # `int` (correct for single-band modes, too narrow for RGBA) --
    # `RGBA`+a 4-tuple is a real, supported Pillow call; only the stub is
    # wrong. Same story for `rounded_rectangle`'s `radius`, which the stubs
    # type as `int` though Pillow accepts (and this drawing wants) a float.
    img = Image.new("RGBA", (size, size), GROUND)  # type: ignore[arg-type]
    draw = ImageDraw.Draw(img)

    safe = size * 0.72
    margin = (size - safe) / 2

    bar_h = safe * 0.16
    gap = safe * 0.14
    total_h = bar_h * 3 + gap * 2
    start_y = margin + (safe - total_h) / 2

    widths = [safe, safe * 0.7, safe * 0.42]  # decreasing -- "aging queue"
    colors = [AMBER, AMBER_DIM_1, AMBER_DIM_2]

    for i, (w, color) in enumerate(zip(widths, colors, strict=True)):
        y0 = start_y + i * (bar_h + gap)
        y1 = y0 + bar_h
        x0 = margin
        x1 = margin + w
        draw.rounded_rectangle([x0, y0, x1, y1], radius=bar_h / 2, fill=color)  # type: ignore[arg-type]

    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _draw_mark(192).save(OUT_DIR / "pwa-192.png")
    _draw_mark(512).save(OUT_DIR / "pwa-512.png")
    _draw_mark(180).save(OUT_DIR / "apple-touch-icon.png")
    print(f"Wrote pwa-192.png, pwa-512.png, apple-touch-icon.png -> {OUT_DIR}")


if __name__ == "__main__":
    main()
