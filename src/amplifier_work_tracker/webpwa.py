"""Progressive Web App support -- manifest, service worker, and icon bytes
-- ported in behaviour from muxplex's PWA pattern (`muxplex/frontend/
manifest.json`, `muxplex/frontend/deck/sw.js`, `muxplex/frontend/index.html`'s
PWA head tags), per explicit request ("take a look at how we did it w/
bkrabach/muxplex as that one seems to work really well as a PWA").

Kept identical to muxplex, deliberately:
  - The service worker CACHES NOTHING. It exists ONLY to satisfy Chrome's
    install-prompt requirement (a `fetch` handler), and every request is
    passed straight through to the network; on failure it falls back to a
    tiny inline offline notice instead of a broken cross-origin error page.
    See `SERVICE_WORKER_JS`'s own comment for the full rationale -- this
    dashboard auto-refreshes every ~20s specifically to surface a live
    alarm the moment it happens (see `webapp.py`'s module docstring), and a
    caching service worker is the single most effective way to manufacture
    a stale-dashboard bug on purpose: it would serve an old snapshot right
    through the very poll that's supposed to catch the alarm.
  - `skipWaiting()` on install, `clients.claim()` on activate -- there is
    no cache version to "wait out".
  - The manifest shape (name/short_name/description/start_url/scope/
    display/background_color/theme_color/icons) -- adapted to this app's
    real ground colour and its own name. Built via `json.dumps` on a real
    dict (not a hand-rolled string) so it can never be invalid JSON.
  - Icons (and the favicon / Open Graph card) served as real PNG/ICO bytes
    from a sibling `webassets/` directory, read once at import time -- the
    same `_FONTS_DIR` / `_font_b64` pattern `webtheme.py` uses for its two
    embedded fonts, applied here to files that must be independently
    fetchable HTTP resources (a manifest icon URL, an `apple-touch-icon`
    link, a favicon) rather than inlined into CSS. Generated from a
    single committed brand source by `scripts/gen_pwa_icons.py` -- see
    that script's own docstring for the full asset pack it derives and
    why the maskable/apple-touch variants are flattened (no transparency).

Deliberate difference from muxplex: no `/deck/`-style nested manifest --
this app has exactly one surface (the dashboard), so one manifest at
`/manifest.json` covers it, same as muxplex's own root manifest (not its
softdeck one).

`webapp.py` wires the eight routes this module's content is served
through (`/manifest.json`, `/sw.js`, `/pwa-192.png`, `/pwa-512.png`,
`/apple-touch-icon.png`, `/favicon.ico`, `/favicon-32.png`,
`/og-dark.png`) and exempts them from PAM auth -- a browser must be able
to fetch the manifest, the service worker, the icons, and the favicon
before (and independent of) any login, or "Add to Home Screen" / install
(and a plain browser tab icon) never works. None of the bytes this module
serves are sensitive.
"""

from __future__ import annotations

import json
import pathlib

# Must match `webtheme.CSS`'s `--color-ground` custom property (v2 dark-mode
# ground). Kept in sync by comment rather than by importing across modules --
# `webtheme.CSS` is a single large raw string this app already treats as a
# self-contained visual-system module (see that module's own docstring); the
# same comment-based-sync convention this codebase already uses elsewhere
# (see `webapp.py`'s `_item_search_key` docstring) applies here.
GROUND_HEX = "#05070f"

_ASSETS_DIR = pathlib.Path(__file__).parent / "webassets"

_MANIFEST: dict[str, object] = {
    "name": "Amplifier Work Tracker",
    "short_name": "Work Tracker",
    "description": (
        "Multi-agent work-queue dashboard -- ready queues, custody, and "
        "alarms across every project."
    ),
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": GROUND_HEX,
    "theme_color": GROUND_HEX,
    "icons": [
        {"src": "/pwa-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/pwa-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        {"src": "/pwa-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
    ],
}

# Built from a real dict via json.dumps rather than hand-assembled as a
# string -- guarantees this is always syntactically valid JSON.
MANIFEST_JSON = json.dumps(_MANIFEST)

# Ported verbatim in behaviour from muxplex's own sw.js (see this module's
# docstring). Text matches the task's own wording for the offline notice.
#
# THE OFFLINE NOTICE CARRIES NO COLOURS, FONT OR SIZE OF ITS OWN, and that is
# deliberate rather than an omission (operator-surface.v1 Core 4, ledger row
# OSV1-005). It used to: a literal near-black ground and off-white ink written
# straight into a `style=` attribute here -- a palette three generations behind
# the live `--color-ground`, which nobody noticed precisely because this
# document only ever renders when the network is down. That is the structural
# trap: this response is produced with NO stylesheet reachable (there is no
# cache, by design, two paragraphs up), so any styling it carries can only ever
# be a SECOND, unverifiable copy of the visual truth. It therefore carries
# none, and asks the user agent for the app's colour scheme instead --
# `<meta name="color-scheme" content="dark light">` makes the browser paint its
# own dark ground and light ink, honouring the reader's system preference
# without this file naming a single value.
SERVICE_WORKER_JS = r"""// amplifier-work-tracker -- minimal service worker.
//
// Exists ONLY to satisfy Chrome's install-PROMPT requirement (the "Add to
// phone" / "Install app" menu item works without a service worker since
// Chrome 108, but Chrome's own installability docs still require a `fetch`
// handler for the automatic install banner/prompt to appear).
//
// Deliberately caches NOTHING. This dashboard auto-refreshes every ~20s and
// exists specifically to surface a live alarm (a held/blocked/deferred
// item) the moment it happens -- see webapp.py's own module docstring. A
// caching service worker is the single most effective way to manufacture a
// stale-dashboard bug on purpose: it would serve an old snapshot right
// through the very poll that's supposed to catch the alarm. Every fetch is
// passed straight through to the network; on failure (offline), fall back
// to a tiny inline offline notice instead of a broken cross-origin error
// page.

self.addEventListener('install', function (event) {
  // Activate immediately -- no version to "wait out", there is no cache.
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', function (event) {
  event.respondWith(
    fetch(event.request).catch(function () {
      return new Response(
        '<!doctype html><meta charset="utf-8">' +
          '<meta name="color-scheme" content="dark light">' +
          '<meta name="viewport" content="width=device-width,initial-scale=1">' +
          '<body><p>' +
          "Can't reach the work tracker right now &mdash; check your connection." +
          '</p></body>',
        { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
      );
    })
  );
});
"""


def icon_bytes(filename: str) -> bytes:
    """Read one of the brand asset files from `webassets/`.

    `filename` must be one of "pwa-192.png", "pwa-512.png",
    "apple-touch-icon.png", "favicon.ico", "favicon-32.png", or
    "og-dark.png" -- the routes in `webapp.py` pass a fixed literal, never
    client input, so no path-traversal handling is needed here.
    """
    return (_ASSETS_DIR / filename).read_bytes()


__all__ = [
    "GROUND_HEX",
    "MANIFEST_JSON",
    "SERVICE_WORKER_JS",
    "icon_bytes",
]
