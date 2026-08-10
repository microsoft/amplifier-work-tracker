"""Puts the repo's `src/` on sys.path so `amplifier_work_tracker` resolves
the same way it does at runtime (foundation's `activate_bundle_package()`
installs the bundle root package editable and adds its `src/` to
`sys.path` before this module's `mount()` ever runs -- see
`docs/BUNDLE_GUIDE.md`, "Bundle with Root Python Package"). Not part of
this module's own installed dependencies (deliberately -- see
`pyproject.toml`'s comment), so local test runs need the same adjustment.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
