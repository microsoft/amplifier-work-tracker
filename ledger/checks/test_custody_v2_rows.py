"""SYNC probe for the public custody-coordination v2/v3 projections.

The stable CCV2 row ids originate with the v2 amendment family. Its current
public representation is the v3 projection, while the v2 projection remains
bound as a historical input. The attestation binds both copies to approved
private-source hashes; this probe carries their public content-hash guards so
a later change cannot bypass the mandatory re-review.
"""

from __future__ import annotations

import json

from ._support import (
    CUSTODY_V2_PROJECTION_PATH,
    CUSTODY_V3_PROJECTION_PATH,
    RATIFICATION_ATTESTATION_PATH,
    REPO_ROOT,
    row,
    sha256,
)


def test_row_ccv2_000() -> None:
    sync = row("CCV2-000")["contract"]
    entries = sync["files"]
    assert [entry["file"] for entry in entries] == [
        "contracts/custody-coordination.v3.public.md",
        "contracts/custody-coordination.v2.public.md",
    ]
    expected = (
        ("v3", CUSTODY_V3_PROJECTION_PATH),
        ("v2", CUSTODY_V2_PROJECTION_PATH),
    )
    attestation = json.loads(RATIFICATION_ATTESTATION_PATH.read_text(encoding="utf-8"))
    for entry, (version, expected_path) in zip(entries, expected, strict=True):
        path = REPO_ROOT / entry["file"]
        assert path == expected_path
        assert sha256(path) == entry["sha256"], (
            f"LEDGER-INTEGRITY: {entry['file']} content hash changed. "
            "Re-review every CCV2 row before updating its hash."
        )
        bound = attestation["versions"][version]
        assert bound["public_projection"] == entry["file"]
        assert bound["public_projection_sha256"] == entry["sha256"]
