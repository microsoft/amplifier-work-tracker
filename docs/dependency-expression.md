# Recommendation: Which Dependency/Link Mechanism to Use

**Status:** ships alongside the `dep`/`work_dep` verb and the `related` field on `add`/`work_add`
(work_tracker items kgi, sx2, 9e4).
**Audience:** anyone declaring a relationship between two work items, by hand or from an agent.

---

## The one idea

amplifier-work-tracker has THREE ways to relate one item to another. They share one underlying
mechanism (a row in bd's `dependencies` table, `type`-tagged) but differ in what they DO at claim
time. Picking the wrong one either silently fails to block work that should wait, or silently
blocks work that should not.

| Mechanism | When to use it | Blocks `work_claim`? | How to create it |
|---|---|---|---|
| **`dep` / `work_dep`** with `dep_type="blocks"` (the default) | A genuinely CANNOT start until B is done | **Yes** -- refuses, naming B | `amplifier-work-tracker dep --project P --id A --depends-on B` / `work_dep(item_id=A, depends_on=B)` |
| **`dep` / `work_dep`** with another `dep_type` (`tracks`, `parent-child`, `until`, `caused-by`, `validates`, ...) | A structural or informational edge that is not itself blocking | No (unless you also separately reason about it) | same verb, `--type <type>` / `dep_type=<type>` |
| **`related` on `add`/`work_add`** (`relates-to` \| `supersedes` \| `follow-up-of`) | A loose cross-reference recorded AT FILING TIME, alongside a brand-new item | No | `add --related` (CLI, if exposed) or `work_add(related=[{"id": B, "kind": "relates-to"}])` |
| **`defer` / `block`** (a DIFFERENT mechanism entirely -- see below) | "This can't proceed right now" with NO other issue involved | N/A -- moves the item's own status, no second issue exists | `defer --reason ...` / `block --reason ...` |

## Why `related`/`follow-up-of` maps to `discovered-from`, not a new bd type

`follow-up-of` is not one of bd's own dependency-type strings. It is semantically identical to
`discovered-from` -- "this item followed on from working on that one" -- which `work_file` already
uses for exactly this relationship, and which bd already treats as non-blocking (see
`adapter.ASSUMPTION` `link.nonblocking`). Reusing it keeps one bd-side vocabulary rather than
inventing a parallel one bd itself does not understand.

## Why `defer`/`block` are NOT dependency edges

A common mistake: creating a dependency on a placeholder/dummy issue just to make an item
disappear from the ready queue for a while. Use `defer`/`block` instead -- they move the item's
OWN status (to a raw bd value `_STATUS_MAP` already recognizes: `deferred`/`blocked`), which is
what makes bd's own status-category system exclude it from `bd ready` (and therefore
`claim_next`), with a REQUIRED reason stored in metadata and visible on an explicit status read.
No second issue is created, and nothing else's dependency graph is touched. Reserve real
dependency edges for "issue B, a real and separately trackable piece of work, must close first."

## Displaying what is already there

`get`/`get_readonly(with_links=True)` returns every dependency AND dependent edge on an item as
`Item.links` -- entries carry `id`/`direction`/`type`/`title`/`status`/`holder`/`blocking`. This is
the read side of everything in the table above except `defer`/`block` (which show up as the
item's own `status` + its reason in metadata, not as a link). The CLI's `list --id` / the
`work_list` tool's `item_id` mode do NOT populate `links` by default (a bulk list never does, to
avoid an N+1 fetch per row) -- use `dep`/`work_dep` (with `depends_on` omitted) for a dedicated,
always-populated read.
