"""Public custody projections bind their published normative bytes to the attestation."""

import hashlib
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ATTESTATION_PATH = _REPO_ROOT / "contracts" / "ratification-attestation.json"
_NORMATIVE_START = b"### Core 8:"
_NORMATIVE_END = b"## Query migration and mounted surface"
_EXPECTED_APPROVALS = {
    "v2": {
        "private_original_document_sha256": (
            "899aa61e574e550cefb48a46b58ea74b9f26500340e15abdaaf701fb5cc990d5"
        ),
        "approved_candidate_identity_sha256": (
            "4a2e2e0de685965348440d03106b4b5db94a82d557f5e6aa19f9bf5cc5b61121"
        ),
        "approved_normative_payload_sha256": (
            "7a4b648e7a77b0bd047ec248f180fa2c9c916ebb63c38d9425ae5a23d4dec830"
        ),
        "public_projection": "contracts/custody-coordination.v2.public.md",
    },
    "v3": {
        "private_original_document_sha256": (
            "5f0937b3b965fd6c89e9273ceb7551a2c7beb15a308a32298b04a0b105e53276"
        ),
        "approved_candidate_identity_sha256": (
            "1f211bfc3ebc04f8abf2238f1b168962222b88b1922a89b899f889fb4eee251a"
        ),
        "approved_normative_payload_sha256": (
            "c174d550ec1b081fd02fff6e4116ac7337930251cb27ce5d5075930e711f2614"
        ),
        "public_projection": "contracts/custody-coordination.v3.public.md",
    },
}


def _normative_payload(data: bytes) -> bytes:
    assert data.count(_NORMATIVE_START) == 1
    assert data.count(_NORMATIVE_END) == 1
    start = data.index(_NORMATIVE_START)
    end = data.index(_NORMATIVE_END)
    assert start < end
    return data[start:end]


def test_public_projections_match_the_attested_approved_normative_payloads() -> None:
    attestation = json.loads(_ATTESTATION_PATH.read_text(encoding="utf-8"))
    assert attestation["projection_kind"] == "non-governing public projection"
    assert set(attestation["versions"]) == {"v2", "v3"}
    assert set(attestation["metadata_redaction_map"]) == {
        "absolute_home_path",
        "session_identifier",
        "private_snapshot_or_lane_locator",
        "candidate_archive_locator",
    }

    for version, entry in attestation["versions"].items():
        assert entry["decision"] == "ratified"
        assert entry["decision_date"] == "2026-09-08"
        for field, approved_value in _EXPECTED_APPROVALS[version].items():
            assert entry[field] == approved_value
        projection = _REPO_ROOT / entry["public_projection"]
        data = projection.read_bytes()

        assert hashlib.sha256(data).hexdigest() == entry["public_projection_sha256"]
        assert (
            hashlib.sha256(_normative_payload(data)).hexdigest()
            == entry["approved_normative_payload_sha256"]
        )
        assert b"NON-GOVERNING PUBLIC PROJECTION" in data
        assert b"does not create a governing contract, authority" in data
