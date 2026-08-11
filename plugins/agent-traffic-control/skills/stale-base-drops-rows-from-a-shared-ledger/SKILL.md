---
name: stale-base-drops-rows-from-a-shared-ledger
description: |
  Trap: a branch that edits a SHARED HAND-EDITED LEDGER — one machine-parseable
  file every session appends rows to (a tracker `data.js`/`data.json`, a
  CHANGELOG, a registry, a manifest, a status board) — can DROP other sessions'
  rows on merge with **no file deletion and a perfectly ordinary diffstat**, so
  a file-level `--diff-filter=D` gate reports clean. This needs a stale **tree**
  (`git reset --soft`, or committing an old worktree with `git add -A`), not
  merely a stale branch point: a branch that is simply behind CONFLICTS loudly
  instead. Distinct from the two sibling stale-base
  skills: `pr-from-stale-branch-silently-reverts-newer-main-files` detects
  whole FILES appearing as deletions in `git diff --stat`, and
  `stale-base-pr-silently-reverts-upstream-content` covers 3-way-merge textual
  overlap WITHIN lines. Here `git diff --diff-filter=D` is EMPTY, the diffstat
  reads like a normal big ledger edit ("800 lines changed"), and the loss is
  whole OBJECTS vanishing plus surviving objects' BODIES rolled back while
  their ids stay put — which an id-only check cannot see. Use when: (1) your
  branch touches a file every parallel session also appends to; (2) you are
  about to merge and the branch has been open more than ~an hour; (3) you are
  auditing after someone else's stale-base merge and need to know whether YOUR
  branch is about to repeat it. The check that matters is a diff against
  **current origin/main**, not against your own base — a diff against your own
  base is clean by construction, and that is the check a session naturally
  runs. Remedy is REBUILD (replay your own edits onto main's file), never
  merge-and-resolve. Timing matters: the window reopens with every PR that
  lands, so the audit belongs immediately before merge, not at wrap-up.
author: Claude Code
version: 1.0.0
date: 2026-08-07
disable-model-invocation: true
---

# A stale base drops rows from a shared ledger — no deletion, no conflict, ordinary diffstat

## Problem

Your repo has one **hand-edited, machine-parseable ledger** that every session
appends to: a progress tracker (`docs/site/assets/data.js`), a registry, a
manifest, a CHANGELOG with structured entries. You branch, splice your rows in,
and merge.

Between your branch point and your merge, four other sessions appended THEIR
rows to the same file. **If your branch's *tree* is stale — not merely its branch
point — your commit genuinely records removing their rows, and git applies that
faithfully with nothing to conflict against.**

> ⚠️ **Be precise about the mechanism, because the loose version of it is false.**
> Merely *being behind* `main` does not do this. Measured on a synthetic shared
> ledger where two sessions append to the same file:
>
> | case | merge-tree | rows survive? |
> |---|---|---|
> | branch appends its own row from a stale base | **exit 1, CONFLICT** | — (loud) |
> | branch regenerates the file from a stale copy | **exit 1, CONFLICT** | — (loud) |
> | **branch's TREE is stale under a current parent** (`git reset --soft`, or committing an old worktree with `git add -A`) | **exit 0, clean** | **LOST** |
>
> Only the third case is silent, and it is silent because the branch *really is*
> asking for the removal — the diff from the merge base contains
> `-{id:'D'}` and `-{id:'E'}` as literal deleted lines. Git is not choosing your
> side; it is doing what your commit says. A branch that is simply behind
> conflicts loudly instead. See `git-diff-2dot-vs-3dot-merge-safety`.

**What still will not warn you, and this is the part worth keeping:**

- `git diff --diff-filter=D --name-only origin/main...HEAD` is **empty** — no
  file was deleted, so a **file-level** gate never fires. This is the real gap:
  the deletion gate catches removed *files*, not reverted *content*.
- The diffstat says `data.js | 800 +++---`, which is exactly what a legitimate
  large ledger edit looks like.
- There is **no merge conflict** in the stale-tree case, for the reason above.
- The repo's own **validator passes** — the payload is structurally valid
  whichever rows are in it. A schema check cannot know a row is missing.
- Every **test suite passes**, because tests do not assert the ledger's contents.
- The diff **against your own base is clean**: additions only. This is the check
  a session naturally runs, and it is the wrong one.

**And the half that survives an id check.** A row can *survive* while its body is
rolled back. Your branch carries an older copy of a task whose `detail` text
another session rewrote; on merge, their rewrite is reverted byte for byte while
the id, the status and the position stay exactly where they were. Nothing that
counts ids or greps for `"id": "..."` sees it.

## Context / Trigger conditions

All of these typically hold:

1. **One file, many appenders.** A ledger/tracker/registry/manifest that every
   session edits by hand as part of its wrap-up ritual.
2. **The file is parseable** (JSON, YAML, TOML, or JSON embedded in JS) — which
   is what makes the reliable check possible at all.
3. **Your branch has been open long enough for someone else to merge.** In a
   busy repo that is under an hour.
4. **Squash-merge flow**, so each sibling merge rewrites main and makes your
   branch progressively staler.
5. **You already rebased once** and believe you are current. Rebasing fixes it
   *at that moment*; the window reopens with the very next merge.

Adjacent symptom, and the reason this is worth its own skill: **the repo has
just had a stale-base incident and everyone is auditing whether they were a
victim.** The question people ask is "did my work survive?" The question that
also needs asking is "**is my open branch about to do it to someone else?**"

## Solution

### Step 1 — Audit against CURRENT main, comparing ids AND bodies

Not against your base. Not `git diff`. **Parse both sides and compare rows.**

```python
#!/usr/bin/env python3
"""Does this branch REMOVE or ROLL BACK any ledger row that main has?"""
import json, re, subprocess, sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
MINE = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
LEDGER = "docs/site/assets/data.js"        # <-- your ledger path
# ids this session legitimately added or edited; everything else must match main
MINE_IDS = {"s-2026-08-07-my-session", "d-my-ruling", "t-my-task"}
COLLECTIONS = ("tasks", "decisions", "sessions", "artifacts")

def load(ref):
    src = subprocess.run(["git", "show", f"{ref}:{LEDGER}"],
                         capture_output=True, text=True, check=True).stdout
    # a bare .json file needs no regex — this unwraps `window.DR = {...};`
    return json.loads(re.search(r"window\.DR\s*=\s*(\{[\s\S]*\})\s*;\s*$", src).group(1))

base, mine, bad = load(BASE), load(MINE), False
for coll in COLLECTIONS:
    b = {r["id"]: r for r in base[coll]}
    m = {r["id"]: r for r in mine[coll]}
    if gone := sorted(set(b) - set(m)):
        print(f"*** {coll}: REMOVED {gone}"); bad = True
    # the half an id check cannot see
    if rolled := [i for i in set(b) & set(m)
                  if b[i] != m[i] and i not in MINE_IDS]:
        print(f"*** {coll}: CHANGED BUT NOT MINE {rolled}"); bad = True
    print(f"{coll:12s} main {len(b):3d} -> mine {len(m):3d}")
sys.exit(1 if bad else 0)
```

Run it **immediately before merging**, and read both kinds of hit:

- `REMOVED` — rows on main that your branch does not have. These die on merge.
- `CHANGED BUT NOT MINE` — rows present on both whose body differs. Diff the
  fields; if main's is newer prose and yours is the older copy, you are about to
  revert someone's edit.

### Step 2 — REBUILD, do not merge-and-resolve

The instinct is to take the conflict and hand-merge the JSON. Don't. Two sides
that both inserted at the head of the same array produce interleaved hunks that
are miserable to reconcile by hand and easy to get subtly wrong.

**Take main's file wholesale, then replay your own edits onto it:**

```sh
git checkout --ours docs/site/assets/data.js      # in a rebase: --ours IS main
python3 scripts/apply_my_rows.py                  # re-run YOUR splicing script
node docs/site/tools/validate_data.mjs
```

This is additive by construction and **cannot revert anyone**, because your
script only ever splices the objects it owns. It also means your ledger edits
should be **scripted rather than hand-typed** in the first place — a script you
can re-run against a newer base is the thing that makes recovery cheap.

If your ledger is hand-formatted (indent + blank lines between entries), splice
the individual object rather than re-serialising the whole payload; a full
`json.dumps` round-trip is usually **not** byte-identical and produces hundreds
of lines of diff that are nobody's change. Verify with a no-op replace first:
render a row, splice it back unchanged, assert the file is byte-identical.

### Step 3 — Re-audit, and expect a second hit

The window reopens with every merge. Re-run step 1 **after** the rebuild and
again if anything lands while you are working. Treat a clean audit as valid
only for the commit you ran it against.

### Step 4 — Verify AFTER the merge, on main

A merged, green PR is not evidence your work survived it — and it is not
evidence you did not damage anyone else's. After merging, re-read main:

```sh
for f in <your files>; do
  git cat-file -e origin/main:"$f" 2>/dev/null && echo "OK   $f" || echo "GONE $f"
done
```

…and re-run step 1's parser against `origin/main` with your session's rows as
the expected additions, asserting each is present **and current** (status
flipped, PR chip filled, text not the pre-session wording).

## Verification

The check is only trustworthy if you have watched it fail. Prove it:

```sh
# stash your branch, take main's ledger, drop one row, re-run the audit
git show origin/main~5:docs/site/assets/data.js > docs/site/assets/data.js
python3 scripts/stale_base_audit.py origin/main HEAD    # must exit 1 and name rows
```

An audit that has only ever printed "clean" is indistinguishable from one that
does not run.

## Example — the routing app PR #848, 2026-08-07

The repo had just had a stale-base incident: **PR #853 reverted 59 files and
5,081 deletions** of already-merged work belonging to at least four sessions,
while green and validated. The owner asked every open session to check whether
its work had been deleted.

A session applying owner rulings to the pig-pose library checked, and its own
work was intact — its PR was still open, so there was nothing of its to delete.
**The check that mattered was the other direction.** Its branch was rebased onto
`b8b86d67`, green, validated, and had been through 41 adversarial review agents.

- Against its **own base**: clean, additions only.
- Against **current `origin/main`**, eight commits later — *including the two
  restore PRs repairing #853* — the same unchanged branch would on merge have
  **removed 3 tasks, 2 decisions, 2 session cards and 8 artifacts** belonging to
  other sessions, and **silently rolled back the detail text of 9 more rows
  whose ids survived**.

`git diff --diff-filter=D` was empty throughout. The diffstat read
`data.js | 800 +++---`. `validate_data.mjs` passed on both sides.

Fixed by taking main's `data.js` and re-running the branch's own splicing
scripts against it. Re-audited clean — **then the audit caught a second instance
mid-run**, because another session added two PR chips to its card while the
check was running. Rebased, re-audited, merged, and verified on main afterwards:
18 files and 12 ledger rows all present and current.

**Lesson:** the near-miss was caught only because the owner asked a question
that reframed the direction of the check. Nothing in the workflow asks it — the
validator cannot, the suites cannot, and the diff a session naturally runs is
against the wrong reference.

## Notes

- **Why the id-only check is not enough**, restated because it is the part that
  gets skipped: a session's rows can all be present and the ledger still be
  damaged, because another session's *edit* to an existing row was reverted. The
  the routing app incident's own restore PRs had to file a separate follow-up (#872,
  "Three in-place edits #853 rolled back on entries that still exist — the
  failure an id check cannot see") after the id-based sweep reported clean.
- **This generalises past trackers** to any hand-edited shared file with
  addressable entries: a CHANGELOG with dated sections, a `mkdocs.yml` nav, an
  `owners` registry, a fixture manifest. The requirement is only that entries
  have stable ids and the file parses.
- **Prefer per-entry files where you can.** A ledger that is one file per row
  (`entries/<id>.json`, assembled at build time) makes this class of loss
  impossible — a stale branch simply lacks the sibling files rather than
  overwriting a shared array. See
  `shared-mutable-index-rmw-race-use-marker-blob-per-item` for the runtime
  version of the same argument.
- The audit is cheap enough to be unconditional: one `git show` per side plus a
  dict comparison, well under a second on a 15,000-line ledger.

## References

- `pr-from-stale-branch-silently-reverts-newer-main-files/SKILL.md` — the
  whole-FILE case, where `git diff --stat` shows deletions. That signal is
  absent here.
- `stale-base-pr-silently-reverts-upstream-content/SKILL.md` — the WITHIN-LINE
  case, where a 3-way merge picks one side's text. Here whole objects go
  missing rather than values inside a line.
- `pr-conflict-from-mid-flight-merges/SKILL.md` — the case where the conflict
  *does* surface before merge.
- `shared-file-redesign-parallel-author-serial-integrate/SKILL.md` — how to
  structure parallel work that must touch one hot file.
