"""Tier-A conformance kit for `contracts/operator-surface.v1.md`.

Tier A is everything assertable in-process: a static pass over `src/`, a token
computation, or an assertion over rendered HTML. Tier B (a real browser, pixel
sweeps, computed contrast, post-swap DOM snapshots) lives beside this package
in `browser/` and is a different lane's work.
"""
