#!/usr/bin/env python3
"""Generate the work-tracker's full brand asset pack from the committed
high-res source icon and write the runtime-served bytes into
`src/amplifier_work_tracker/webassets/` -- the same "real file, read once at
import time" convention `webtheme.py` already uses for its two embedded
fonts (`_FONTS_DIR` / `_font_b64`), applied here to bytes that must be
independently fetchable HTTP resources (manifest icons, favicons, an
apple-touch-icon, an Open Graph card) rather than inlined into CSS.

Run this manually whenever the mark needs to change:

    python3 scripts/gen_pwa_icons.py

Requires Pillow. Deliberately NOT a runtime (or even `dev`/`web` extra)
dependency of this package -- asset generation is a one-time/occasional
build step the maintainer runs locally, not something the running
dashboard, its tests, or its CI needs. Install it ad hoc to regenerate:
`pip install --user Pillow` (or use any Python that already has it).

THE SOURCE: `assets/branding/source/amplifier-work-tracker-icon-1966.png`
-- a 1966x1966 RGBA master (a stylised ribbon "A" beside three horizontal
task-bar pills, on a dark rounded-square/"squircle" ground with a thin
black outline stroke), committed so the whole pack below is reproducible
from one file. Replaces the previous placeholder generator, which *drew*
an amber-bars mark from scratch; this one *derives* every size/format from
that committed master via high-quality LANCZOS downscaling -- no drawing.

WHAT GETS PRODUCED (mirrors bkrabach/muxplex's `assets/branding/` layout,
also seen in microsoft/amplifier and bkrabach/cortex -- this project has no
native macOS/Windows app, so their `.icns`/`.ico`-tray/menu-bar entries are
skipped; everything actually served over HTTP is kept):

    assets/branding/
      icons/work-tracker-icon-{16,22,24,32,48,64,128,192,256,512,1024}.png
      favicons/{favicon.ico, favicon-16.png, favicon-32.png, favicon-48.png,
                apple-touch-icon.png}
      pwa/{pwa-192.png, pwa-512.png}
      og/og-dark.png

Two render modes:

  * `_resize` -- a straight LANCZOS downscale, keeping the source's native
    alpha (its transparent rounded-corner margin). Used for anything that
    is allowed to have its own shape/transparency: the generic icon set,
    small favicon PNGs, and the manifest's 192px "any"-purpose PWA icon.

  * `_flatten` -- downscales, then alpha-composites onto a fully OPAQUE
    `ICON_GROUND`-filled square of the same size. Used exactly where
    transparency is a bug, not a feature:
      - `apple-touch-icon.png`: iOS does not honour the alpha channel on
        home-screen icons -- transparent pixels render as solid black,
        not "see-through". Flattening avoids black-cornered icons on iOS.
      - `pwa-512.png`: the manifest (see `webpwa.py`) references this same
        file for BOTH `purpose: "maskable"` and `purpose: "any"`. A
        maskable icon must be a full-bleed opaque square per the W3C/
        Android spec -- the OS applies its own mask shape (circle,
        squircle, ...) and undefined/inconsistent things happen with
        transparency underneath. A flattened square also reads perfectly
        well as the plain "any" icon, so one file safely serves both.

MASKABLE SAFE ZONE: verified (both by direct visual inspection of the
source and by numeric HSV-based bounding-box analysis of its non-ground
pixels) that the glyph's outermost pixel sits ~12-13% in from every edge
of the 1966px source -- comfortably inside the ~80%-diameter "safe zone"
Android/W3C expect for a maskable icon (>=10% margin per side). No extra
padding is added beyond what `_flatten` already does (filling the
source's own already-transparent corner margin); the glyph itself is
never repositioned or shrunk.
"""

from __future__ import annotations

import pathlib

from PIL import Image

ROOT = pathlib.Path(__file__).parent.parent
SOURCE = ROOT / "assets" / "branding" / "source" / "amplifier-work-tracker-icon-1966.png"
BRANDING_DIR = ROOT / "assets" / "branding"
ICONS_DIR = BRANDING_DIR / "icons"
FAVICONS_DIR = BRANDING_DIR / "favicons"
PWA_DIR = BRANDING_DIR / "pwa"
OG_DIR = BRANDING_DIR / "og"
RUNTIME_DIR = ROOT / "src" / "amplifier_work_tracker" / "webassets"

# Short brand slug used in the `icons/` filenames -- mirrors muxplex's
# `muxplex-icon-*.png` / cortex's `cortex-icon-*.png` convention, matching
# this app's own `short_name` ("Work Tracker") in `webpwa.py`'s manifest.
SLUG = "work-tracker"

# Exactly the sizes muxplex/cortex/microsoft-amplifier ship in `icons/`.
ICON_SIZES = [16, 22, 24, 32, 48, 64, 128, 192, 256, 512, 1024]
FAVICON_ICO_SIZES = [16, 32, 48]

# The source icon's OWN baked-in background fill colour -- measured as the
# median RGB of the master PNG's non-glyph (low-saturation-or-low-value)
# opaque pixels: (0, 5, 26) / "#00051a", matching the "~#000411 deep
# dark-blue" the requester described by eye. Used ONLY by `_flatten` to
# fill the source's already-transparent rounded-corner margin, so the fill
# is invisible/seamless against the master's own interior -- never used to
# recolour the manifest, the CSS, or anything else.
#
# Deliberately DISTINCT from `webpwa.GROUND_HEX` / `webtheme.CSS`'s
# `--ground` (`#0D0D0C`, the app's real UI chrome colour, used for the
# manifest's `background_color`/`theme_color` and the page `<body>`). The
# two near-blacks are close enough not to clash, but are NOT reconciled
# into one value: the manifest's background/theme colour should keep
# matching the actual app chrome a user sees after launch, not the
# icon artwork's own internal padding colour.
ICON_GROUND = (0x00, 0x05, 0x1A, 0xFF)


def _load_source() -> Image.Image:
    return Image.open(SOURCE).convert("RGBA")


def _resize(im: Image.Image, size: int) -> Image.Image:
    """High-quality downscale, preserving the source's native alpha."""
    return im.resize((size, size), Image.Resampling.LANCZOS)


def _flatten(im: Image.Image, size: int) -> Image.Image:
    """Downscale, then composite onto a fully opaque `ICON_GROUND` square
    of the same size -- see this module's docstring for which outputs
    need this and why."""
    resized = _resize(im, size)
    # Pillow's bundled type stubs declare `new(...)`'s `color` param as
    # `int` (correct for single-band modes, too narrow for RGBA) -- RGBA
    # + a 4-tuple is a real, supported Pillow call; only the stub is wrong.
    canvas = Image.new("RGBA", (size, size), ICON_GROUND)  # type: ignore[arg-type]
    canvas.alpha_composite(resized)
    return canvas


def _og_card(im: Image.Image) -> Image.Image:
    """1200x630 Open Graph / social-preview card: the icon, native alpha,
    centred on the icon's own brand ground."""
    width, height = 1200, 630
    icon_size = 440
    canvas = Image.new("RGBA", (width, height), ICON_GROUND)  # type: ignore[arg-type]
    icon = _resize(im, icon_size)
    x = (width - icon_size) // 2
    y = (height - icon_size) // 2
    canvas.alpha_composite(icon, (x, y))
    return canvas


def _save(im: Image.Image, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def main() -> None:
    src = _load_source()

    # -- icons/ : general-purpose icon set, native alpha ------------------
    for size in ICON_SIZES:
        _save(_resize(src, size), ICONS_DIR / f"{SLUG}-icon-{size}.png")

    # -- favicons/ ---------------------------------------------------------
    favicon_pngs: dict[int, Image.Image] = {}
    for size in FAVICON_ICO_SIZES:
        rendered = _resize(src, size)
        favicon_pngs[size] = rendered
        _save(rendered, FAVICONS_DIR / f"favicon-{size}.png")

    # Multi-resolution .ico bundling 16/32/48. Pillow's ICO writer takes a
    # base image plus a `sizes` list and resizes internally per frame; feed
    # it the largest pre-resized frame (48px) we already made at full
    # LANCZOS quality so it is only ever downsampling, never upsampling.
    FAVICONS_DIR.mkdir(parents=True, exist_ok=True)
    favicon_pngs[max(FAVICON_ICO_SIZES)].save(
        FAVICONS_DIR / "favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in FAVICON_ICO_SIZES],
    )

    # apple-touch-icon.png -- flattened (opaque): see module docstring.
    _save(_flatten(src, 180), FAVICONS_DIR / "apple-touch-icon.png")

    # -- pwa/ ----------------------------------------------------------------
    # 192: "any"-purpose only in the manifest -- native alpha keeps the
    # source's own rounded-square-plus-stroke look.
    _save(_resize(src, 192), PWA_DIR / "pwa-192.png")
    # 512: shared by the manifest for BOTH `maskable` and `any` -- must be
    # flattened (see module docstring).
    _save(_flatten(src, 512), PWA_DIR / "pwa-512.png")

    # -- og/ -------------------------------------------------------------
    _save(_og_card(src), OG_DIR / "og-dark.png")

    # -- runtime copies -- exactly the bytes webapp.py's routes serve -------
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    runtime_sources = {
        "pwa-192.png": PWA_DIR / "pwa-192.png",
        "pwa-512.png": PWA_DIR / "pwa-512.png",
        "apple-touch-icon.png": FAVICONS_DIR / "apple-touch-icon.png",
        "favicon.ico": FAVICONS_DIR / "favicon.ico",
        "favicon-32.png": FAVICONS_DIR / "favicon-32.png",
        "og-dark.png": OG_DIR / "og-dark.png",
    }
    for name, path in runtime_sources.items():
        (RUNTIME_DIR / name).write_bytes(path.read_bytes())

    print(f"Wrote {len(ICON_SIZES)} icons/*.png -> {ICONS_DIR}")
    print(f"Wrote favicons/* (ico + 16/32/48 + apple-touch) -> {FAVICONS_DIR}")
    print(f"Wrote pwa/{{pwa-192.png, pwa-512.png}} -> {PWA_DIR}")
    print(f"Wrote og/og-dark.png -> {OG_DIR}")
    print(f"Copied {len(runtime_sources)} runtime assets -> {RUNTIME_DIR}")


if __name__ == "__main__":
    main()
