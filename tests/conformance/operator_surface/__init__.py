"""Tier-A conformance kit for `contracts/operator-surface.v1.md`.

Tier A is everything assertable in-process: a static pass over `src/`, a token
computation, or an assertion over rendered HTML. Tier B (a real browser, pixel
sweeps, computed contrast, post-swap DOM snapshots) lives beside this package
in `browser/`, is marked `tier_b`, and runs as its own tier via
`make test-conformance-b`.
"""
