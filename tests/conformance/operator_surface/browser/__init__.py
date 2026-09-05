"""Tier-B (real-browser) conformance kit for `contracts/operator-surface.v1.md`.

The contract names this package's `test_tier_b.py` by path in Conformance 1,
2, 3 and 4 and in Freeze 2. Everything else here exists to serve it:

  `_png.py`      a dependency-free PNG decoder + colour histogram, so a pixel
                 sweep is a NUMBER this repo computed, not an eyeball verdict.
  `_probe.py`    the in-page JavaScript that measures contrast, target boxes,
                 overflow, motion and live regions, plus the pure-Python
                 re-checks that read those numbers back.
  `_artifacts.py`  the on-disk artifact contract (Freeze 3).
  `conftest.py`  the app-on-an-ephemeral-port + pinned-chromium fixtures.

Read `test_tier_b.py`'s module docstring for the rules this kit runs under --
in particular: no assertion in this package may rest on a screenshot being
LOOKED at. A screenshot is evidence; the artifact is the measurement.
"""
