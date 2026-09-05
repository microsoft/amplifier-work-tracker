"""Conformance kits -- one package per governed contract.

A conformance kit is NOT another unit tier. Its checks are named by a
`contracts/*.md` clause's own **Machine check:** line, and each one ships as a
DISCRIMINATING PAIR: a good half asserted against the real artifact, and a bad
half asserted against a deliberately-wrong one that the same check must
report. A check nobody has watched fail is a check that might assert nothing.

A kit may span tiers: `operator_surface/` holds the in-process Tier-A checks,
and its real-browser Tier-B half lives beside them in
`operator_surface/browser/` as its own `tier_b`-marked tier.
"""
