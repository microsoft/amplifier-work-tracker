# Custody and Coordination Contract — v2

> **NON-GOVERNING PUBLIC PROJECTION.** This is a publication copy of an
> already-ratified source. It does not create a governing contract, authority,
> ratification, or freeze. Its Core and Conformance clauses reproduce the
> approved source byte-for-byte. The binding hashes and the metadata-redaction
> categories are recorded in [`ratification-attestation.json`](ratification-attestation.json).

**Recorded disposition:** RATIFIED (decision date: 2026-09-08)

**Projection scope:** This non-governing publication copy carries the approved
v2 amendments for public inspection. The public historical
[`custody-coordination.v1.md`](custody-coordination.v1.md) remains unchanged.

**Publication provenance:** The approved candidate identity and the
privately-held original's document hash are bound by the attestation. Raw
candidate bytes are not published in this projection.

---

## Ratified amendments to v1

### Core 8: In-process recovery from reclaim is discoverable and actionable

A session that loses custody via reclaim discovers the loss and recovers
in-process. The loss is discoverable via the passive query
`work_query(kind="status")` returning `holding.custody_lost: true` and
actionable without manual intervention or session restart.

### Core 13: Every custody interaction goes through the `work_*` tool seam

All capability to mutate, claim, release, resolve, or query items is exposed
through the tool seam (`work_claim`, `work_resolve`, `work_release`,
`work_declare`, `work_query`, `work_item`, etc.).
`work_query(kind="status")`, `work_query(kind="stats")`,
`work_query(kind="list")`, and `work_query(kind="item")` are the passive query
forms. A capability reachable only via raw `bd` CLI or internal API is a
missing verb — the missing verb is the bug.

### Conformance 1: Conflicted-but-landed close

**Verification:** Call `work_resolve(id)`, capture the exception, then call
`work_query(kind="item", item_id=id)` to verify the item is actually closed.
This item query is read-only and does not claim, mutate, or touch custody.

### Conformance 3: In-process recovery after reclaim

**Scenario:** A session holds an item, the reclaim sweep runs and strips
custody, and the session calls the passive query
`work_query(kind="status")` to check status.

**Verification:** Claim → trigger reclaim →
`work_query(kind="status")` → verify `holding.custody_lost: true` is detected
and the recovery path exists.

## Query migration and mounted surface

The former passive query tool names are replaced, not retained as mounted
runtime aliases: `work_status()` becomes `work_query(kind="status")`;
`work_stats(project)` becomes `work_query(kind="stats", project=project)`;
`work_list(project, status, limit)` becomes
`work_query(kind="list", project=project, status=status, limit=limit)`; and
`work_list(project, item_id=id)` becomes
`work_query(kind="item", project=project, item_id=id)`.

The mounted tool surface is exactly eleven tools: `work_claim`, `work_declare`,
`work_resolve`, `work_reopen`, `work_erratum`, `work_release`, `work_query`,
`work_item`, `work_tracker`, `work_add`, and `work_file`. `work_query` accepts
exactly the four query kinds `status`, `stats`, `list`, and `item`;
`work_item` carries item-administration operations; and `work_tracker` carries
tracker operations. The old standalone query, item-administration, tracker,
and subscription tool names are not mounted.

## What does not change

- Claim remains a single atomic operation; this version changes no claim or
  custody-write semantics.
- Reclaim, the one-strike renewal rule, `holding.custody_lost` loss signaling,
  and in-process recovery via `work_release` remain required.
- Fencing against stale holders and the requirement that custody writes verify
  by readback remain unchanged.
- Item-by-ID reads remain passive and read-only: they do not claim, mutate, or
  touch custody.
- The `work_*` tool seam remains the required public seam; raw `bd` CLI and
  internal-API bypasses remain prohibited.

## Changelog

- **2026-09-08 — RATIFIED (recorded source disposition).** This non-governing
  publication copy preserves the approved passive-query migration, eleven-tool
  mounted surface, and conformance wording. Its binding is the public
  `contracts/ratification-attestation.json`; raw candidate bytes remain
  privately held.