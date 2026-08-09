"""Small, dependency-free helpers shared by the CLI-surface tests.

Kept out of conftest.py because these are plain functions, not fixtures.
"""

from __future__ import annotations

import re
import subprocess

_ERROR_WORD_RE = re.compile(r"\berror\b", re.IGNORECASE)


def looks_like_error_text(text: str) -> bool:
    return bool(_ERROR_WORD_RE.search(text or ""))


def assert_no_silent_failure(result: subprocess.CompletedProcess) -> None:
    """The invariant this whole tier exists to enforce: a command that
    prints error-looking text must never also report success (exit 0).

    This is precisely the shape of the two shipped bugs this suite is
    named to prevent from recurring: `amplifier-work-tracker reap` printed
    `Error: unknown command "reclaim"` to stderr and still exited 0.
    """
    combined = (result.stdout or "") + (result.stderr or "")
    if looks_like_error_text(combined):
        assert result.returncode != 0, (
            "command printed error-looking text but exited 0 (this is "
            "exactly the silent-failure shape amplifier-work-tracker shipped before): "
            f"{combined[:500]!r}"
        )
