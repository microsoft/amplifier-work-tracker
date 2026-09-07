# Proposed patch — `publication_readback.sh` prefers a STALE sha over the fresh one it already has

**Filed as** `model_performance-lsda` (root cause of the already-open
`model_performance-17oq`; same mechanism as `model_performance-fr47`).

**Shipped here as an artifact, not applied.** The script lives in
`openai-evals-team-ci`, which this lane must not edit
(GOAL.md SCOPE-OUTS: *"do not edit files outside the paths this lane owns"*;
the same clause says to ship the patch under the lane's artifact root and
report it).

---

## Reproduced live, 2026-09-07

`git push` landed `ce0bf88bfa223a4b0f35794a2c102ab6c220469f` on
`microsoft/amplifier-work-tracker`, branch `lane/hd-work-tracker`. Immediately
after:

```
$ publication_readback.sh -C . lane/hd-work-tracker
  "head_sha": "1ab580f4cd9e519938503595bb1c037b73e2a07d"      # the PREVIOUS commit
  exit 0

$ git ls-remote --heads https://github.com/microsoft/amplifier-work-tracker.git lane/hd-work-tracker
ce0bf88bfa223a4b0f35794a2c102ab6c220469f    refs/heads/lane/hd-work-tracker

$ gh pr view 95 --repo microsoft/amplifier-work-tracker --json headRefOid
{"headRefOid":"ce0bf88bfa223a4b0f35794a2c102ab6c220469f", ...}    # seconds later
```

The remote was already correct. The script still printed the previous commit
and exited 0 — the exact shape `17oq` predicts, and the exact shape
`merge_gate.sh` would then fail the lane on.

## Root cause — the script throws away its own authoritative read

From `tools/publication_readback.sh`, the trailing python heredoc:

```python
pub = {
    ...
    "head_sha": sha,                       # <- from git ls-remote. Correct, fresh.
}
if prs:
    p = prs[0]
    ...
    if p.get("headRefOid"):
        pub["head_sha"] = p["headRefOid"]  # <- OVERWRITES it with gh pr list's value
```

`gh pr list`'s `headRefOid` is served from GitHub's API and lags a push;
`git ls-remote` speaks to the git remote and does not. The script does the
authoritative read first, then discards it in favour of the laggy one.

This also contradicts the script's own header: *"the marker's publication
values must come from a read of the remote"*.

## Two candidate fixes

### (a) Minimal — delete the overwrite

```diff
     if prs:
         p = prs[0]
         pub["pr_number"] = p["number"]
         pub["pr_url"] = p["url"]
         pub["pr_state"] = ("draft " if p.get("isDraft") else "") + str(p.get("state", "")).lower()
         pub["verified_by"] += (f"; gh pr list --repo {slug} --head {branch} "
                                f"--state all --json number,url,state,headRefOid")
-        if p.get("headRefOid"):
-            pub["head_sha"] = p["headRefOid"]
```

Three lines out. `head_sha` then always comes from `git ls-remote`, which is
what the header promises and what `merge_gate.sh` re-reads against.

### (b) Better — keep both, and FAIL LOUD when they disagree (recommended)

```diff
     if prs:
         p = prs[0]
         pub["pr_number"] = p["number"]
         pub["pr_url"] = p["url"]
         pub["pr_state"] = ("draft " if p.get("isDraft") else "") + str(p.get("state", "")).lower()
         pub["verified_by"] += (f"; gh pr list --repo {slug} --head {branch} "
                                f"--state all --json number,url,state,headRefOid")
-        if p.get("headRefOid"):
-            pub["head_sha"] = p["headRefOid"]
+        pr_sha = p.get("headRefOid")
+        if pr_sha and pr_sha != sha:
+            sys.stderr.write(
+                f"WARNING: the branch head and the PR head DISAGREE.\n"
+                f"  git ls-remote (authoritative): {sha}\n"
+                f"  gh pr list  headRefOid:        {pr_sha}\n"
+                f"  head_sha below is the ls-remote value. If this persists for\n"
+                f"  more than a few seconds after a push it is NOT API lag -- the\n"
+                f"  PR is not tracking the branch head (force-push mid-flight, or\n"
+                f"  a cross-fork PR: see model_performance-fr47).\n")
```

**Recommended: (b).** A genuine disagreement is real information — it means the
PR's head is not the branch head — and silently choosing *either* value is the
class of failure this whole toolchain exists to prevent. `(a)` fixes the stale
sha; `(b)` fixes it and stops the next reader having to rediscover why the two
numbers ever differ. Everything else in this toolchain names a disagreement
rather than resolving it quietly; this should too.

## Why it matters beyond cosmetics

`merge_gate.sh` re-reads every marker claim against GitHub and exits non-zero
when one does not hold. A lane that pastes this script's output verbatim —
**which the goal template instructs it to do** — can therefore fail the gate
for a publication that is perfectly correct.

This lane caught it only because it re-read `git ls-remote` by hand and noticed
the mismatch. That is not a check the template asks for, so the next lane will
not do it.

## What this lane did about it, in the meantime

`DONE.json`'s `publication.head_sha` carries the value **`git ls-remote` and
`gh pr view` agree on**, re-read after the final push — not the value
`publication_readback.sh` printed. `verified_by` names both commands.
